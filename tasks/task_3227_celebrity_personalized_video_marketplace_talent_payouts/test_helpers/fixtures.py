"""Composite setup builders and the pytest fixtures that expose them.

Every builder drives the public API only; there is no direct database access
anywhere in this suite.  Builders use ``get_success_data`` so a setup step
the PRD allows to answer 200 or 201 is not pinned to one of them.

Identity threading: once a talent or buyer record exists, every ownership-
gated call on it uses ``make_talent_headers(record["id"])`` /
``make_buyer_headers(record["id"])`` — never a shared constant.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_INITIAL_INSTANT
from .test_users import (
    ADMIN,
    MODERATOR,
    make_buyer_headers,
    make_talent_headers,
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


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(client, to_iso8601, headers=ADMIN):
    """Move the logical clock forward to ``to_iso8601``."""
    response = client.set_clock(to_iso8601, headers=headers)
    assert response.status_code in (200, 201), (
        "setting the logical clock to {0} failed with {1}: {2}".format(
            to_iso8601, response.status_code, response.text
        )
    )
    return to_iso8601


# ─── Talent onboarding ────────────────────────────────────────────────────


def register_talent(client, headers=None, **overrides):
    """Create a PENDING_VERIFICATION talent.  Returns the talent record."""
    if headers is None:
        headers = make_talent_headers("test-talent-register")
    response = client.create_talent(f.talent_payload(**overrides), headers=headers)
    return get_success_data(response)


def talent_headers(talent):
    return make_talent_headers(talent["id"])


def buyer_headers(buyer):
    return make_buyer_headers(buyer["id"])


def read_talent(client, talent_id, headers=ADMIN):
    return get_success_data(client.get_talent(talent_id, headers=headers))


def read_buyer(client, buyer_id, headers=ADMIN):
    return get_success_data(client.get_buyer(buyer_id, headers=headers))


def read_order(client, order_id, headers=ADMIN):
    return get_success_data(client.get_order(order_id, headers=headers))


def submit_identity(client, talent, **overrides):
    response = client.submit_identity(
        talent["id"],
        overrides.get("identity_document_ref", talent.get("identity_document_ref") or "doc-resubmit"),
        headers=talent_headers(talent),
    )
    return get_success_data(response)


def submit_tax_document(client, talent, decision="VERIFY", **overrides):
    """Submit a tax document and (by default) have an admin review it.

    Returns the final TaxDocument record (VERIFIED unless decision overrides).
    """
    response = client.submit_tax_document(
        talent["id"], f.tax_document_payload(**overrides), headers=talent_headers(talent)
    )
    doc = get_success_data(response)
    if decision is not None:
        response = client.review_tax_document(doc["id"], decision, headers=ADMIN)
        doc = get_success_data(response)
    return doc


def set_rates(client, talent, **overrides):
    """Set rates with a fresh OCC version read.  Returns the updated talent."""
    current = read_talent(client, talent["id"])
    overrides.setdefault("expected_talent_version", current["version"])
    response = client.set_rates(
        talent["id"], f.rates_payload(**overrides), headers=talent_headers(talent)
    )
    return get_success_data(response)


def activate_talent(client, talent, headers=ADMIN):
    response = client.activate_talent(talent["id"], headers=headers)
    return get_success_data(response)


def create_active_talent(client, rates_overrides=None, **talent_overrides):
    """Full onboarding: register, identity, verified tax doc, rates, activate.

    Returns the ACTIVE talent record.
    """
    talent = register_talent(client, **talent_overrides)
    talent = submit_identity(client, talent)
    submit_tax_document(client, talent, decision="VERIFY")
    talent = set_rates(client, talent, **(rates_overrides or {}))
    return activate_talent(client, talent)


# ─── Buyers ───────────────────────────────────────────────────────────────


def register_buyer(client, is_business_account=False, **overrides):
    response = client.create_buyer(
        f.buyer_payload(is_business_account=is_business_account, **overrides),
        headers=make_buyer_headers("test-buyer-register"),
    )
    return get_success_data(response)


# ─── Orders: staged progression ───────────────────────────────────────────


def create_order(client, talent, buyer, use_type="PERSONAL", **overrides):
    response = client.create_order(
        f.order_payload(talent["id"], buyer["id"], use_type=use_type, **overrides),
        headers=buyer_headers(buyer),
    )
    return get_success_data(response)


def create_screened_order(client, talent, buyer, use_type="PERSONAL", **overrides):
    """Create an order and attest its screening.  Returns AWAITING_ACCEPTANCE."""
    order = create_order(client, talent, buyer, use_type=use_type, **overrides)
    response = client.screening_attest(
        order["id"], order["screening_token"], headers=buyer_headers(buyer)
    )
    return get_success_data(response)


def create_accepted_order(client, talent, buyer, use_type="PERSONAL", **overrides):
    """Create + attest + accept.  Returns ACCEPTED order."""
    order = create_screened_order(client, talent, buyer, use_type=use_type, **overrides)
    response = client.accept_order(order["id"], headers=talent_headers(talent))
    return get_success_data(response)


def create_delivered_order(
    client, talent, buyer, use_type="PERSONAL", moderate="CLEAR", **overrides
):
    """Create + attest + accept + upload.  Returns (order, video).

    ``moderate`` may be ``None`` (leave the video PENDING_REVIEW), ``"CLEAR"``
    or ``"FLAG"``; moderation runs as the platform admin.
    """
    order = create_accepted_order(client, talent, buyer, use_type=use_type, **overrides)
    video_overrides = {
        k: v for k, v in overrides.items() if k in ("content_url", "duration_seconds")
    }
    response = client.upload_video(
        order["id"], f.video_payload(**video_overrides), headers=talent_headers(talent)
    )
    video = get_success_data(response)
    if moderate is not None:
        if moderate == "FLAG":
            moderate_video_flag(client, video, flagged_reason="off-brand remark")
        else:
            moderate_video_clear(client, video)
    order = read_order(client, order["id"])
    return order, video


def create_confirmed_order(client, talent, buyer, use_type="PERSONAL", **overrides):
    """Full happy path through CONFIRMED.  Returns (order, video)."""
    order, video = create_delivered_order(
        client, talent, buyer, use_type=use_type, moderate="CLEAR", **overrides
    )
    response = client.confirm_order(order["id"], headers=buyer_headers(buyer))
    order = get_success_data(response)
    return order, video


def moderate_video_clear(client, video, headers=ADMIN):
    response = client.moderate_video(video["id"], "CLEAR", headers=headers)
    return get_success_data(response)


def moderate_video_flag(client, video, flagged_reason="policy breach", headers=ADMIN):
    response = client.moderate_video(
        video["id"], "FLAG", flagged_reason=flagged_reason, headers=headers
    )
    return get_success_data(response)


def deliver_video(client, talent, order, **video_overrides):
    """Upload the next video on an order; returns the Video record."""
    response = client.upload_video(
        order["id"], f.video_payload(**video_overrides), headers=talent_headers(talent)
    )
    return get_success_data(response)


# ─── Disputes ─────────────────────────────────────────────────────────────


def open_dispute(client, buyer, order, reason="video does not match the request"):
    """Open a dispute with a fresh OCC version read.  Returns the Dispute."""
    current = read_order(client, order["id"])
    response = client.open_dispute(
        current["id"], reason, current["version"], headers=buyer_headers(buyer)
    )
    return get_success_data(response)


# ─── Payouts ──────────────────────────────────────────────────────────────


def run_payout_sweep(client, period_start=CLOCK_INITIAL_INSTANT,
                     period_end="2026-09-08T00:00:00Z"):
    """Run the weekly sweep; returns the list of created Payout records."""
    response = client.payout_sweep(period_start, period_end, headers=ADMIN)
    assert response.status_code == 200, (
        "payout sweep failed with {0}: {1}".format(response.status_code, response.text)
    )
    body = response.json()
    data = body["data"]
    assert isinstance(data, list), "the sweep returns the created payouts as a list"
    return data


def payout_lines_for_talent(client, talent, **params):
    """The talent's payout lines via the per-talent listing."""
    response = client.list_talent_payout_lines(
        talent["id"], headers=ADMIN, params=params or None
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def lines_for_order(client, order_id):
    """All payout lines tied to one order, via the admin-wide listing."""
    response = client.list_payout_lines(headers=ADMIN, params={"order_id": order_id})
    assert response.status_code == 200
    return response.json()["data"]
