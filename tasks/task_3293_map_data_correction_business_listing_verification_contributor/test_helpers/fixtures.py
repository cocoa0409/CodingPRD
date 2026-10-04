"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the runner restarts the server (empty database) before each test.

Fixtures use get_success_data() (lenient) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    create_contributor_payload,
    create_hours_observation_payload,
    create_imagery_task_payload,
    create_listing_payload,
    create_map_edit_payload,
    create_region_payload,
    create_review_flag_payload,
    create_review_payload,
    create_review_ticket_payload,
    create_routing_update_payload,
    create_suspension_payload,
    create_verification_attempt_payload,
)
from .test_users import (
    TEST_USERS,
    make_business_owner_headers,
    make_contributor_headers,
    make_moderator_headers,
    make_policy_analyst_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
MOD1 = TEST_USERS["moderator_headers"]


def _fail(msg, resp):
    raise AssertionError(f"Setup failed: {msg}; status={resp.status_code}; body={resp.text[:400]}")


def _ok(resp, msg):
    if resp.status_code >= 400:
        _fail(msg, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: simple creators
# ---------------------------------------------------------------------------

def make_region(name="Region", **overrides):
    """Create a region. Returns the region dict."""
    payload = create_region_payload(name=name, **overrides)
    resp = api_client.create_region(payload, ADMIN)
    return _ok(resp, f"create_region({name})")


def make_contributor(region_id, display_name="Contributor", email=None, seed_points=None):
    """Register a contributor; optionally seed total points via an ADJUSTMENT
    grant (POSTED, default multiplier 1.0). Returns the contributor dict."""
    if email is None:
        email = f"{display_name.lower().replace(' ', '-')}-{region_id[:8]}@example.com"
    resp = api_client.create_contributor(
        create_contributor_payload(
            display_name=display_name, email=email, home_region_id=region_id
        ),
        ANON,
    )
    contributor = _ok(resp, f"create_contributor({display_name})")
    if seed_points:
        resp = api_client.create_contributor_grant(
            {
                "contributor_id": contributor["id"],
                "source_type": "ADJUSTMENT",
                "source_id": f"seed-{seed_points}",
                "base_points": seed_points,
                "note": "seed points for level setup",
            },
            ADMIN,
        )
        _ok(resp, f"seed {seed_points} points")
        resp = api_client.get_contributor(contributor["id"], ADMIN)
        contributor = _ok(resp, "re-read contributor after seed")
    return contributor


def make_listing(region_id, name="Listing", **overrides):
    """Create a business listing. Returns the listing dict."""
    payload = create_listing_payload(region_id=region_id, name=name)
    payload.update(overrides)
    resp = api_client.create_listing(payload, ADMIN)
    return _ok(resp, f"create_listing({name})")


def get_listing(listing_id):
    resp = api_client.get_listing(listing_id, ADMIN)
    return _ok(resp, f"get_listing({listing_id})")


def get_contributor(contributor_id):
    resp = api_client.get_contributor(contributor_id, ADMIN)
    return _ok(resp, f"get_contributor({contributor_id})")


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return _ok(resp, f"set_clock({to_iso8601})")


# ---------------------------------------------------------------------------
# Tier 2: listing lifecycle (claim / verify / suspend / appeal)
# ---------------------------------------------------------------------------

def claim_listing(listing, owner_id):
    """Claim an UNCLAIMED listing as owner contributor owner_id.
    Returns the updated listing."""
    owner_headers = make_business_owner_headers(owner_id)
    resp = api_client.claim_listing(
        listing["id"],
        {"expected_listing_version": listing["version"]},
        owner_headers,
    )
    return _ok(resp, "claim_listing")


def verify_listing(listing_id, owner_id, method="POSTCARD"):
    """Issue a verification attempt and submit the minted code.
    Returns (verified_listing, attempt)."""
    owner_headers = make_business_owner_headers(owner_id)
    resp = api_client.create_verification_attempt(
        create_verification_attempt_payload(listing_id=listing_id, method=method),
        owner_headers,
    )
    attempt = _ok(resp, "create_verification_attempt")
    resp = api_client.submit_verification_code(
        attempt["id"], {"code": attempt["code"]}, owner_headers
    )
    attempt = _ok(resp, "submit_verification_code")
    listing = get_listing(listing_id)
    return listing, attempt


def make_verified_listing(region_id, owner_id, name="Verified Listing", method="POSTCARD",
                          **listing_overrides):
    """Create + claim + verify a listing. Returns (listing, owner_id)."""
    listing = make_listing(region_id, name=name, **listing_overrides)
    listing = claim_listing(listing, owner_id)
    listing, _attempt = verify_listing(listing["id"], owner_id, method=method)
    return listing, owner_id


def suspend_listing(listing_id, analyst_id="pa-1", violation_type="FAKE_ADDRESS",
                    evidence_notes="policy evidence"):
    """Suspend a listing as a PolicyAnalyst. Returns the SuspensionCase."""
    resp = api_client.suspend_listing(
        listing_id,
        create_suspension_payload(
            violation_type=violation_type, evidence_notes=evidence_notes
        ),
        make_policy_analyst_headers(analyst_id),
    )
    return _ok(resp, f"suspend_listing({violation_type})")


def appeal_case(case_id, owner_id, appeal_text=None):
    if appeal_text is None:
        appeal_text = (
            "This appeal statement is deliberately long enough to pass the "
            "fifty character minimum length requirement."
        )
    resp = api_client.appeal_suspension_case(
        case_id, {"appeal_text": appeal_text}, make_business_owner_headers(owner_id)
    )
    return _ok(resp, "appeal_suspension_case")


def start_appeal_review(case_id, analyst_id="pa-2"):
    resp = api_client.start_appeal_review(case_id, make_policy_analyst_headers(analyst_id))
    return _ok(resp, "start_appeal_review")


def decide_case(case_id, analyst_id="pa-2", decision="UPHELD"):
    resp = api_client.decide_suspension_case(
        case_id, {"decision": decision}, make_policy_analyst_headers(analyst_id)
    )
    return _ok(resp, f"decide_case({decision})")


# ---------------------------------------------------------------------------
# Tier 3: map edits and review-queue machinery
# ---------------------------------------------------------------------------

def make_map_edit(listing, contributor_id, edit_type="ATTRIBUTE", payload=None,
                  expected_listing_version=None):
    """Submit a map edit. Defaults to an ATTRIBUTE edit with no evidence URLs
    (auto-validation score 55 for a fresh-trust contributor -> QUEUED).
    Returns the created MapEdit.

    When expected_listing_version is omitted, the listing's *current* version
    is re-read: per PRD §2.5 the edit create bumps the listing version, so a
    previously captured listing dict is already stale after one edit."""
    if payload is None:
        payload = {"attribute": "wifi", "value": True}
    if expected_listing_version is None:
        expected_listing_version = get_listing(listing["id"])["version"]
    resp = api_client.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"],
            contributor_id=contributor_id,
            edit_type=edit_type,
            payload=payload,
            expected_listing_version=expected_listing_version,
        ),
        make_contributor_headers(contributor_id),
    )
    return _ok(resp, f"create_map_edit({edit_type})")


def make_auto_published_edit(listing, contributor_id, edit_type="ATTRIBUTE",
                             attribute="wifi"):
    """Submit an ATTRIBUTE edit carrying 3 evidence URLs so the
    auto-validation score reaches exactly 85 -> PUBLISHED. Returns the edit."""
    return make_map_edit(
        listing,
        contributor_id,
        edit_type=edit_type,
        payload={"attribute": attribute, "value": True,
                 "evidence_urls": ["u1", "u2", "u3"]},
    )


def open_edit_review_ticket(edit_id, moderator_id="mod-1"):
    """Create (and thereby claim) an EDIT_REVIEW ticket on a QUEUED edit.
    Returns the ticket."""
    resp = api_client.create_review_ticket(
        create_review_ticket_payload(queue="EDIT_REVIEW", map_edit_id=edit_id),
        make_moderator_headers(moderator_id),
    )
    return _ok(resp, "open_edit_review_ticket")


def resolve_ticket(ticket_id, moderator_id, resolution):
    resp = api_client.resolve_review_ticket(
        ticket_id, {"resolution": resolution}, make_moderator_headers(moderator_id)
    )
    return _ok(resp, f"resolve_ticket({resolution})")


def make_rejected_edit(listing, contributor_id, moderator_id="mod-1",
                       attribute="wifi"):
    """Submit an edit routed to QUEUED, then have a moderator reject it.
    Returns the (REJECTED) edit."""
    edit = make_map_edit(
        listing, contributor_id,
        payload={"attribute": attribute, "value": True},
    )
    ticket = open_edit_review_ticket(edit["id"], moderator_id)
    resolve_ticket(ticket["id"], moderator_id, "REJECT")
    resp = api_client.get_map_edit(edit["id"], ADMIN)
    return _ok(resp, "re-read rejected edit")


# ---------------------------------------------------------------------------
# Tier 4: reviews, flags, moderation
# ---------------------------------------------------------------------------

def make_review(listing_id, contributor_id, rating=4, text=None):
    if text is None:
        text = "A solid experience overall; the staff were friendly and quick."
    resp = api_client.create_review(
        create_review_payload(
            listing_id=listing_id, contributor_id=contributor_id,
            rating=rating, text=text,
        ),
        make_contributor_headers(contributor_id),
    )
    return _ok(resp, "create_review")


def flag_review(review_id, flagger_id, reason="SPAM"):
    resp = api_client.flag_review(
        review_id, create_review_flag_payload(reason=reason),
        make_contributor_headers(flagger_id),
    )
    return _ok(resp, "flag_review")


def open_moderation_ticket(flag_id, moderator_id="mod-1"):
    """Create (and claim) a REVIEW_MODERATION ticket on an OPEN flag, pulling
    the review into UNDER_MODERATION. Returns the ticket."""
    resp = api_client.create_review_ticket(
        create_review_ticket_payload(queue="REVIEW_MODERATION", review_flag_id=flag_id),
        make_moderator_headers(moderator_id),
    )
    return _ok(resp, "open_moderation_ticket")


# ---------------------------------------------------------------------------
# Tier 5: hours observations, imagery, routing
# ---------------------------------------------------------------------------

def make_hours_observation(listing_id, source, day_mask="1111100",
                           open_time="09:00", close_time="17:00",
                           as_contributor_id=None):
    """Record an hours observation. When as_contributor_id is given the call
    is made as that Contributor (needed for CONTRIBUTOR-source observations
    whose author level drives priority promotion); otherwise PlatformAdmin."""
    headers = (
        make_contributor_headers(as_contributor_id)
        if as_contributor_id is not None
        else ADMIN
    )
    resp = api_client.create_hours_observation(
        create_hours_observation_payload(
            listing_id=listing_id, source=source, day_mask=day_mask,
            open_time=open_time, close_time=close_time,
        ),
        headers,
    )
    return _ok(resp, f"create_hours_observation({source})")


def make_imagery_task(region_id, collection_zone="zone-A", operator_id="op-1",
                      window_start="2026-09-02T00:00:00Z",
                      window_end="2026-09-05T00:00:00Z",
                      blur_obligation="FACES_AND_PLATES"):
    resp = api_client.create_imagery_task(
        create_imagery_task_payload(
            region_id=region_id, collection_zone=collection_zone,
            operator_id=operator_id, window_start=window_start,
            window_end=window_end, blur_obligation=blur_obligation,
        ),
        TEST_USERS["imagery_operator_headers"]
        if operator_id == "op-1"
        else make_operator_headers(operator_id),
    )
    return _ok(resp, "create_imagery_task")


def make_operator_headers(operator_id):
    from prd_bench_local_runner.testing import build_user_headers

    return build_user_headers(operator_id, "ImageryOperator")


def schedule_imagery_task(task_id, operator_id="op-1"):
    resp = api_client.schedule_imagery_task(task_id, make_operator_headers(operator_id))
    return _ok(resp, "schedule_imagery_task")


def capture_imagery_task(task_id, capture_media_count, operator_id="op-1"):
    resp = api_client.capture_imagery_task(
        task_id, {"capture_media_count": capture_media_count},
        make_operator_headers(operator_id),
    )
    return _ok(resp, "capture_imagery_task")


def blur_complete_imagery_task(task_id, blurred_media_count, operator_id="op-1",
                               reprocess=False):
    payload = {"blurred_media_count": blurred_media_count}
    if reprocess:
        payload["reprocess"] = True
    resp = api_client.blur_complete_imagery_task(
        task_id, payload, make_operator_headers(operator_id)
    )
    return _ok(resp, "blur_complete_imagery_task")


def publish_imagery_task(task_id, operator_id="op-1"):
    resp = api_client.publish_imagery_task(task_id, make_operator_headers(operator_id))
    return _ok(resp, "publish_imagery_task")


def get_region(region_id):
    resp = api_client.get_region(region_id, ADMIN)
    return _ok(resp, "get_region")


def make_routing_update(region, segment_ref="S1", kind="CLOSURE",
                        effective_start="2026-10-01T00:00:00Z",
                        effective_end="2026-10-02T00:00:00Z",
                        expected_region_version=None, **extra):
    if expected_region_version is None:
        expected_region_version = region["version"]
    payload = create_routing_update_payload(
        region_id=region["id"], segment_ref=segment_ref, kind=kind,
        effective_start=effective_start, effective_end=effective_end,
        expected_region_version=expected_region_version,
    )
    payload.update(extra)
    resp = api_client.create_routing_update(
        payload, TEST_USERS["routing_engineer_headers"]
    )
    return _ok(resp, "create_routing_update")
