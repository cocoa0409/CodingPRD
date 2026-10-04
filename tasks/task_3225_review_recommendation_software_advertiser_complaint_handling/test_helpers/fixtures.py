"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each pytest test runs against a freshly restarted server). Setup
calls use get_success_data so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_DEFAULT
from .factories import (
    create_business_page_payload,
    create_call_event_payload,
    create_campaign_payload,
    create_complaint_payload,
    create_consumer_alert_payload,
    create_impression_payload,
    create_page_claim_payload,
    create_review_payload,
    create_solicitation_case_payload,
    create_user_payload,
)
from .test_users import (
    TEST_USERS,
    make_advertiser_headers,
    make_business_owner_headers,
    make_reporter_headers,
    make_reviewer_headers,
)

OPS = TEST_USERS["platform_ops_headers"]
ADMIN = TEST_USERS["support_admin_headers"]
MODERATOR = TEST_USERS["content_moderator_headers"]
INVESTIGATOR = TEST_USERS["trust_investigator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_DEFAULT):
    """Pin the logical clock (PRD §2.4)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, OPS))


def create_user(trust_score=None, **overrides):
    """Create a user; optionally pin trust_score via the ops trust adjustment."""
    user = get_success_data(api.create_user(create_user_payload(**overrides), OPS))
    if trust_score is not None:
        user = get_success_data(
            api.adjust_trust(user["id"], {"trust_score": trust_score}, OPS)
        )
    return user


def create_page(**overrides):
    return get_success_data(api.create_business_page(create_business_page_payload(**overrides), OPS))


def create_review(page_id, author_id, **overrides):
    return get_success_data(
        api.create_review(page_id, create_review_payload(**overrides), make_reviewer_headers(author_id))
    )


def get_page(page_id):
    return get_success_data(api.get_business_page(page_id, OPS))


def get_review(review_id):
    return get_success_data(api.get_review(review_id, OPS))


def get_user(user_id):
    return get_success_data(api.get_user(user_id, OPS))


# ---------------------------------------------------------------------------
# Tier 2: page ownership
# ---------------------------------------------------------------------------

def claim_page(page_id, owner_id):
    """File a CLAIM for owner_id, verify it, approve it. Returns the APPROVED claim."""
    claim = get_success_data(
        api.create_page_claim(page_id, create_page_claim_payload(kind="CLAIM"),
                              make_business_owner_headers(owner_id))
    )
    claim = get_success_data(
        api.verify_page_claim(claim["id"], {"verification_code": claim["verification_code"]},
                              make_business_owner_headers(owner_id))
    )
    page = get_page(page_id)
    claim = get_success_data(
        api.approve_page_claim(claim["id"], {"expected_page_version": page["version"]}, ADMIN)
    )
    return claim


def setup_claimed_page(page_overrides=None):
    """Create owner + page, claim it. Returns (page, owner)."""
    owner = create_user()
    page = create_page(**(page_overrides or {}))
    claim_page(page["id"], owner["id"])
    return get_page(page["id"]), owner


# ---------------------------------------------------------------------------
# Tier 3: advertising stack
# ---------------------------------------------------------------------------

def setup_ad_account(budget_cents=10000, page_overrides=None):
    """Claimed page + ad account. Returns (page, owner, account)."""
    page, owner = setup_claimed_page(page_overrides)
    account = get_success_data(
        api.create_ad_account(page["id"], {"daily_budget_cents": budget_cents},
                              make_business_owner_headers(owner["id"]))
    )
    return page, owner, account


def setup_active_campaign(kind="SPONSORED_PLACEMENT", bid_cents=100,
                          starts_on="2026-09-01", ends_on="2026-09-30",
                          budget_cents=100000):
    """Claimed page + ad account + one ACTIVE campaign.

    Returns (page, owner, account, campaign). The logical clock must already
    be inside [starts_on, ends_on] for activation to succeed.
    """
    page, owner, account = setup_ad_account(budget_cents)
    campaign = get_success_data(
        api.create_campaign(
            account["id"],
            create_campaign_payload(
                kind=kind,
                bid_cents=bid_cents,
                starts_on=starts_on,
                ends_on=ends_on,
                call_tracking_enabled=(kind == "CALL_TRACKING"),
            ),
            make_advertiser_headers(owner["id"]),
        )
    )
    campaign = get_success_data(
        api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
    )
    return page, owner, account, campaign


def charge_impression(account_id, campaign_id, idempotency_key):
    return api.create_impression(
        account_id,
        create_impression_payload(campaign_id=campaign_id, idempotency_key=idempotency_key),
        OPS,
    )


def record_call(account_id, campaign_id, called_at, duration_seconds, caller_number="+15550001000"):
    return api.create_call_event(
        account_id,
        create_call_event_payload(
            campaign_id=campaign_id,
            caller_number=caller_number,
            called_at=called_at,
            duration_seconds=duration_seconds,
        ),
        OPS,
    )


# ---------------------------------------------------------------------------
# Tier 4: complaint workflow
# ---------------------------------------------------------------------------

def setup_complaint(review_state_target="FILTERED", kind="FILTERED_DISPUTE",
                    rating=2, author_trust=50):
    """Claimed page + a review in the target recommendation state + an
    UNDER_REVIEW complaint of the given kind filed by the owner.

    author_trust=50 -> at-submission score 500 -> FILTERED; author_trust=100
    -> 700 -> DISPLAYED. Returns (page, owner, author, review, complaint).
    """
    page, owner = setup_claimed_page()
    author = create_user(trust_score=author_trust)
    review = create_review(page["id"], author["id"], rating=rating)
    complaint = get_success_data(
        api.create_complaint(page["id"],
                             create_complaint_payload(review_id=review["id"], kind=kind),
                             make_business_owner_headers(owner["id"]))
    )
    complaint = get_success_data(api.start_review_complaint(complaint["id"], MODERATOR))
    return page, owner, author, review, complaint


# ---------------------------------------------------------------------------
# Tier 5: solicitation workflow
# ---------------------------------------------------------------------------

def setup_confirmed_case(author_trust=50, rating=2):
    """Page + review by author + CONFIRMED solicitation case targeting it.

    Returns (page, author, reporter, review, case). Confirming fires the full
    cascade: review REMOVED + evidence_confirmed, author strike/trust penalty,
    auto consumer alert on the page.
    """
    page = create_page()
    author = create_user(trust_score=author_trust)
    reporter = create_user()
    review = create_review(page["id"], author["id"], rating=rating)
    case = get_success_data(
        api.create_solicitation_case(
            page["id"],
            create_solicitation_case_payload(target_review_ids=[review["id"]]),
            make_reporter_headers(reporter["id"]),
        )
    )
    case = get_success_data(api.investigate_case(case["id"], INVESTIGATOR))
    case = get_success_data(api.confirm_case(case["id"], INVESTIGATOR))
    return get_page(page["id"]), get_user(author["id"]), reporter, get_review(review["id"]), case
