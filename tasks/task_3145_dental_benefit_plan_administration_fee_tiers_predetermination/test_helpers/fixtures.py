"""Composite setup builders and the pytest fixtures that expose them.

Every builder drives the public API only — there is no direct database
access anywhere in this suite.  Builders use ``get_success_data`` so that a
setup step the PRD allows to answer 200 or 201 does not have to be pinned
to one of the two at every call site.

The central builder is ``standard_stack``: a running test harness kills the
API server process and re-launches it before every individual test, so each
test starts against an empty database and must rebuild the world — an
ACTIVE plan, an ACTIVE fee schedule for the provider's tier, an ACTIVE
provider, and an enrolled subscriber — from scratch.

Identity threading: the Member and Provider roles are entity-backed, so any
ownership-gated call is made with ``make_provider_headers(provider["id"])``
or ``make_member_headers(subscriber["id"])`` — never with a shared
constant.
"""

import pytest

from .api_client import ApiClient
from .assertions import get_success_data
from . import factories as f
from .constants import (
    CATEGORY_BASIC,
    CATEGORY_MAJOR,
    CATEGORY_PREVENTIVE,
    CDT_CROWN_MAJOR,
    CDT_FILING_BASIC,
    CDT_PERIODIC_EVAL,
    COB_PRIMARY,
    TIER_PPO,
)
from .test_users import (
    ADMIN,
    EXAMINER,
    NETWORK,
    REVIEWER_1,
    REVIEWER_2,
    make_member_headers,
    make_provider_headers,
    make_reviewer_headers,
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


def set_clock(client, to_iso8601):
    """Advance the logical clock; the response carries the new time."""
    resp = client.set_clock(to_iso8601, headers=ADMIN)
    return get_success_data(resp)


def reset_clock(client):
    """Return the logical clock to a deterministic instant for the test."""
    return set_clock(client, f.instant(2026, 1, 1))


# ─── Single-entity builders ───────────────────────────────────────────────


def create_plan(client, **overrides):
    """Create a plan (born DRAFT) and return its body."""
    resp = client.create_plan(f.create_plan_payload(**overrides), headers=ADMIN)
    return get_success_data(resp)


def create_active_plan(client, **overrides):
    """Create a plan and move it to ACTIVE."""
    plan = create_plan(client, **overrides)
    resp = client.activate_plan(plan["id"], headers=ADMIN)
    return get_success_data(resp)


def create_provider(client, **overrides):
    """Register a provider (born ACTIVE) and return its body."""
    resp = client.create_provider(f.create_provider_payload(**overrides), headers=NETWORK)
    return get_success_data(resp)


def create_fee_schedule(client, entries=None, **overrides):
    """File a fee schedule (born PENDING) and return its body."""
    resp = client.create_fee_schedule(
        f.create_fee_schedule_payload(entries=entries, **overrides), headers=NETWORK
    )
    return get_success_data(resp)


def create_active_fee_schedule(client, entries=None, **overrides):
    """File a fee schedule and move it to ACTIVE."""
    schedule = create_fee_schedule(client, entries=entries, **overrides)
    resp = client.activate_fee_schedule(schedule["id"], headers=NETWORK)
    return get_success_data(resp)


def create_subscriber(client, plan_id, **overrides):
    """Enroll a subscriber on an ACTIVE plan and return its body."""
    resp = client.create_subscriber(
        f.create_subscriber_payload(plan_id, **overrides), headers=ADMIN
    )
    return get_success_data(resp)


def create_dependent(client, subscriber_id, **overrides):
    """Add a dependent under a subscriber and return its body."""
    resp = client.create_dependent(
        subscriber_id, f.create_dependent_payload(**overrides), headers=ADMIN
    )
    return get_success_data(resp)


def create_limitation_rule(client, plan_id, **overrides):
    """Attach a limitation rule to a plan and return its body."""
    resp = client.create_limitation_rule(
        plan_id, f.create_limitation_rule_payload(**overrides), headers=ADMIN
    )
    return get_success_data(resp)


def create_predetermination(client, subscriber_id, provider, **overrides):
    """Submit a predetermination as the rendering provider themselves."""
    resp = client.create_predetermination(
        f.create_predetermination_payload(subscriber_id, provider["id"], **overrides),
        headers=make_provider_headers(provider["id"]),
    )
    return get_success_data(resp)


def assign_predetermination(client, predet_id, reviewer_id="rev-1"):
    """A ClinicalReviewer self-assigns; returns the UNDER_REVIEW body."""
    resp = client.assign_predetermination(
        predet_id,
        {"clinical_reviewer_id": reviewer_id},
        headers=make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def reassign_predetermination(client, predet_id, reviewer_id="rev-2"):
    """Reassign to a different reviewer; returns the refreshed body."""
    resp = client.reassign_predetermination(
        predet_id,
        {"clinical_reviewer_id": reviewer_id},
        headers=make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def approve_predetermination(client, predet_id, version, reviewer_id="rev-1"):
    """Approve with the OCC version pin; returns the APPROVED body."""
    resp = client.approve_predetermination(
        predet_id,
        {"expected_predetermination_version": version},
        headers=make_reviewer_headers(reviewer_id),
    )
    return get_success_data(resp)


def create_claim(client, subscriber_id, provider, lines=None, **overrides):
    """Submit a claim as the rendering provider; returns the claim body."""
    resp = client.create_claim(
        f.create_claim_payload(subscriber_id, provider["id"], lines=lines, **overrides),
        headers=make_provider_headers(provider["id"]),
    )
    return get_success_data(resp)


def read_claim(client, claim_id):
    resp = client.get_claim(claim_id, headers=EXAMINER)
    return get_success_data(resp)


def read_predetermination(client, predet_id, headers=None):
    resp = client.get_predetermination(predet_id, headers=headers or REVIEWER_1)
    return get_success_data(resp)


def read_provider(client, provider_id):
    resp = client.get_provider(provider_id, headers=NETWORK)
    return get_success_data(resp)


def read_subscriber(client, subscriber_id):
    resp = client.get_subscriber(subscriber_id, headers=ADMIN)
    return get_success_data(resp)


def read_dependent(client, dependent_id):
    resp = client.get_dependent(dependent_id, headers=ADMIN)
    return get_success_data(resp)


def read_fee_schedule(client, schedule_id):
    resp = client.get_fee_schedule(schedule_id, headers=NETWORK)
    return get_success_data(resp)


def claim_lines(client, claim_id, params=None):
    """The claim's lines sorted by line_number ascending."""
    resp = client.list_claim_lines(claim_id, headers=EXAMINER, params=params)
    return get_success_data(resp)


def subscriber_accumulators(client, subscriber_id, params=None):
    resp = client.list_subscriber_accumulators(
        subscriber_id, headers=EXAMINER, params=params
    )
    return get_success_data(resp)


def pay_claim(client, claim_id):
    resp = client.pay_claim(claim_id, headers=EXAMINER)
    return get_success_data(resp)


def void_claim(client, claim_id, expected_version):
    resp = client.void_claim(
        claim_id, {"expected_claim_version": expected_version}, headers=EXAMINER
    )
    return get_success_data(resp)


def upload_attachment(client, claim_id, provider, claim_line_id, **overrides):
    resp = client.create_claim_attachment(
        claim_id,
        f.create_attachment_payload(claim_line_id, **overrides),
        headers=make_provider_headers(provider["id"]),
    )
    return get_success_data(resp)


# ─── The standard stack ───────────────────────────────────────────────────


def standard_stack(client, plan_overrides=None, entries=None, subscriber_overrides=None,
                   clock="2026-01-01T00:00:00Z"):
    """Rebuild the world from an empty database.

    Returns a dict with keys ``plan``, ``provider``, ``schedule``,
    ``subscriber``.  The defaults are the profile most tests want: an ACTIVE
    plan with no waiting periods and ABP off; an ACTIVE PPO fee schedule
    effective 2026-01-01 carrying D0120 PREVENTIVE 5000, D2391 BASIC 10000
    and D2740 MAJOR 10000 (no attachments, no ABP alternates); an ACTIVE PPO
    provider; and a PRIMARY subscriber effective 2026-01-01.
    """
    if clock is None:
        reset_clock(client)
    else:
        set_clock(client, clock)
    plan = create_active_plan(client, **(plan_overrides or {}))
    provider = create_provider(client)
    if entries is None:
        entries = [
            f.fee_schedule_entry_payload(
                cdt_code=CDT_PERIODIC_EVAL, allowed_cents=5000,
                category=CATEGORY_PREVENTIVE,
            ),
            f.fee_schedule_entry_payload(
                cdt_code=CDT_FILING_BASIC, allowed_cents=10000,
                category=CATEGORY_BASIC,
            ),
            f.fee_schedule_entry_payload(
                cdt_code=CDT_CROWN_MAJOR, allowed_cents=10000,
                category=CATEGORY_MAJOR,
            ),
        ]
    schedule = create_active_fee_schedule(client, entries=entries)
    subscriber = create_subscriber(client, plan["id"], **(subscriber_overrides or {}))
    return {
        "plan": plan,
        "provider": provider,
        "schedule": schedule,
        "subscriber": subscriber,
    }


def standard_stack_attachment_required(client, cdt_code=CDT_CROWN_MAJOR, allowed=10000):
    """Standard stack whose schedule requires an attachment for ``cdt_code``."""
    entries = [
        f.fee_schedule_entry_payload(
            cdt_code=cdt_code, allowed_cents=allowed,
            category=CATEGORY_MAJOR, requires_attachment=True,
        ),
    ]
    return standard_stack(client, entries=entries)


def standard_predetermination(client, stack, **overrides):
    """A SUBMITTED predetermination on the standard stack."""
    return create_predetermination(
        client, stack["subscriber"]["id"], stack["provider"], **overrides
    )


def under_review_predetermination(client, stack, reviewer_id="rev-1", **overrides):
    """A predetermination assigned to a reviewer (UNDER_REVIEW)."""
    predet = standard_predetermination(client, stack, **overrides)
    return assign_predetermination(client, predet["id"], reviewer_id)


def approved_predetermination(client, stack, reviewer_id="rev-1", **overrides):
    """A predetermination walked to APPROVED."""
    under_review = under_review_predetermination(
        client, stack, reviewer_id=reviewer_id, **overrides
    )
    return approve_predetermination(
        client, under_review["id"], under_review["version"], reviewer_id
    )


def adjudicated_claim(client, stack, lines=None, **overrides):
    """A claim that auto-adjudicated on submission (PRIMARY coverage)."""
    return create_claim(
        client, stack["subscriber"]["id"], stack["provider"], lines=lines, **overrides
    )


def paid_claim(client, stack, lines=None, **overrides):
    """An adjudicated claim walked to PAID."""
    claim = adjudicated_claim(client, stack, lines=lines, **overrides)
    return pay_claim(client, claim["id"])
