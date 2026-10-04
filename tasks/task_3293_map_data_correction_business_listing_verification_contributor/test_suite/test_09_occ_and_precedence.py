"""Optimistic concurrency control and validation-precedence tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_listing,
    create_map_edit_payload,
    create_routing_update_payload,
    get_listing,
    get_region,
    make_business_owner_headers,
    make_contributor,
    make_contributor_headers,
    make_listing,
    make_map_edit,
    make_region,
    make_routing_update,
    make_verified_listing,
    suspend_listing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RE1 = TEST_USERS["routing_engineer_headers"]


def test_stale_name_edit_on_suspended_listing_reports_suspension(api):
    """PRD §3.4: "The target listing must admit edits — listings in
    `SUSPENDED` or `PERMANENTLY_CLOSED` refuse new edits with
    `ERR_LISTING_SUSPENDED` (HTTP 409) — and the submitter must be `ACTIVE`."
    PRD §3.2: "Listing names are screened for keyword stuffing: a name
    containing two or more consecutive uppercase keyword tokens drawn from the
    service-keyword list — the canonical offender looks like "BEST CHEAP PIZZA
    NEAR ME" — is rejected with `ERR_KEYWORD_STUFFING` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_pair_listing_suspended_beats_keyword_stuffing
    """
    region = make_region(name="R9")
    owner = make_contributor(region["id"], display_name="C10", email="c10@x.com")
    writer = make_contributor(region["id"], display_name="C11", email="c11@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Salon Nine", method="VIDEO")
    suspend_listing(listing["id"], analyst_id="pa-1", violation_type="FAKE_ADDRESS",
                    evidence_notes="mail returned undeliverable twice")
    current = get_listing(listing["id"])
    assert current["status"] == "SUSPENDED"

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=writer["id"],
            edit_type="NAME", payload={"name": "BEST CHEAP Salon Nine"},
            expected_listing_version=current["version"],
        ),
        make_contributor_headers(writer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_SUSPENDED)


def test_suspended_listing_refuses_clean_edit_too(api):
    """PRD §3.4: "The target listing must admit edits — listings in
    `SUSPENDED` or `PERMANENTLY_CLOSED` refuse new edits with
    `ERR_LISTING_SUSPENDED` (HTTP 409) — and the submitter must be `ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/state_pair_listing_suspended_beats_keyword_stuffing
    """
    region = make_region(name="R9b")
    owner = make_contributor(region["id"], display_name="C10b", email="c10b@x.com")
    writer = make_contributor(region["id"], display_name="C11b", email="c11b@x.com")
    listing, _ = make_verified_listing(region["id"], owner["id"],
                                       name="Salon Nine B", method="VIDEO")
    suspend_listing(listing["id"], analyst_id="pa-1", violation_type="FAKE_ADDRESS",
                    evidence_notes="mail returned undeliverable twice")
    current = get_listing(listing["id"])

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=writer["id"],
            edit_type="ATTRIBUTE", payload={"attribute": "wifi", "value": True},
            expected_listing_version=current["version"],
        ),
        make_contributor_headers(writer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_SUSPENDED)


def test_stale_version_beats_keyword_stuffing_on_same_call(api):
    """PRD §2.6: "This ordering matters operationally: a request that is both
    unauthenticated and malformed returns the authentication error, and a
    stale-version rejection surfaces before a keyword-stuffing rejection on
    the same call."
    PRD §2.5: "Creating a map edit requires `expected_listing_version`,
    carrying the client's last observed `version` of the target listing; if
    the listing's current `version` has advanced since that read — because
    another edit was published against it, the listing was claimed, or it was
    suspended — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so
    the stale write is refused rather than silently layered over a listing
    state the client never saw."

    Design: Difficulty/priority_pair_validation_conflict/temporal_pair_appeal_window_beats_nothing_but_safety_beats_referential
    """
    region = make_region(name="R10")
    contributor = make_contributor(region["id"], display_name="C12", email="c12@x.com")
    listing = make_listing(region["id"], name="Bakery Ten")
    stale_version = listing["version"]
    # A legitimate edit bumps the listing's version.
    make_map_edit(listing, contributor["id"], edit_type="HOURS",
                  payload={"day_mask": "1111100", "open_time": "08:00",
                           "close_time": "18:00"})
    current = get_listing(listing["id"])
    assert current["version"] == stale_version + 1

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="NAME", payload={"name": "BEST CHEAP Bakery Ten"},
            expected_listing_version=stale_version,
        ),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_listing(listing["id"])
    assert after["keyword_stuffing_strikes"] == 0, (
        "the stuffing screen must not run once the stale-version check fires"
    )


def test_stale_version_on_map_edit_after_publish_bump(api):
    """PRD §2.5: "Creating a map edit requires `expected_listing_version`,
    carrying the client's last observed `version` of the target listing; if
    the listing's current `version` has advanced since that read — because
    another edit was published against it, the listing was claimed, or it was
    suspended — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so
    the stale write is refused rather than silently layered over a listing
    state the client never saw."
    PRD §3.4: "The listing's `version` increments on the edit's creation,
    keeping §2.5 honest for the next writer."

    Design: Corner/validations/stale_version_on_map_edit_after_publish_bump
    """
    region = make_region(name="ROccE")
    contributor = make_contributor(region["id"], display_name="CE", email="occ@x.com")
    listing = make_listing(region["id"], name="OCC Edit Biz")
    stale_version = listing["version"]
    # Auto-published edit (score 85) bumps the listing version.
    first = make_map_edit(listing, contributor["id"],
                          payload={"attribute": "a", "value": 1,
                                   "evidence_urls": ["u1", "u2", "u3"]})
    assert first["status"] == "PUBLISHED"

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="HOURS",
            payload={"day_mask": "1111111", "open_time": "09:00",
                     "close_time": "17:00"},
            expected_listing_version=stale_version,
        ),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_stale_version_on_claim(api):
    """PRD §2.5: "Claiming an unclaimed listing likewise requires
    `expected_listing_version`, and a claim built on an outdated snapshot —
    one taken before another claim or a suspension mutated the listing — is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_on_claim
    """
    region = make_region(name="ROccC")
    owner_a = make_contributor(region["id"], display_name="O1", email="o1@x.com")
    owner_b = make_contributor(region["id"], display_name="O2", email="o2@x.com")
    listing = make_listing(region["id"], name="OCC Biz")
    stale_version = listing["version"]

    first = api.claim_listing(
        listing["id"], {"expected_listing_version": stale_version},
        make_business_owner_headers(owner_a["id"]),
    )
    claimed = validate_success(first)
    assert claimed["status"] == "CLAIM_PENDING"

    second = api.claim_listing(
        listing["id"], {"expected_listing_version": stale_version},
        make_business_owner_headers(owner_b["id"]),
    )
    validate_error(second, ApiErrorId.ERR_STALE_VERSION)


def test_stale_version_on_routing_create_after_version_bump(api):
    """PRD §2.5: "Proposing a routing update requires
    `expected_region_version` matching the region's current `version`; routing
    data is epoch-versioned, and a proposal built on a stale epoch must
    restart from a fresh read, again surfacing `ERR_STALE_VERSION` (HTTP
    412)."
    PRD §3.9: "a proposal built on a stale region epoch is refused with
    `ERR_STALE_VERSION`, and a successful create increments the region's
    `version`."

    Design: Corner/validations/stale_version_on_routing_create_after_version_bump
    """
    region = make_region(name="ROccR")
    stale_version = region["version"]
    make_routing_update(region, segment_ref="S9", kind="TURN_RESTRICTION",
                        effective_start="2026-10-01T00:00:00Z",
                        effective_end="2026-10-02T00:00:00Z",
                        restriction_detail={"from_segment": "S9",
                                            "to_segment": "S10",
                                            "turn": "LEFT"})

    resp = api.create_routing_update(
        create_routing_update_payload(
            region_id=region["id"], segment_ref="S11", kind="CLOSURE",
            effective_start="2026-10-05T00:00:00Z",
            effective_end="2026-10-06T00:00:00Z",
            expected_region_version=stale_version,
        ),
        RE1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_stale_version_beats_keyword_stuffing_on_name_edit(api):
    """PRD §2.6: "This ordering matters operationally: a request that is both
    unauthenticated and malformed returns the authentication error, and a
    stale-version rejection surfaces before a keyword-stuffing rejection on
    the same call."
    PRD §2.5: "Creating a map edit requires `expected_listing_version`,
    carrying the client's last observed `version` of the target listing; if
    the listing's current `version` has advanced since that read — because
    another edit was published against it, the listing was claimed, or it was
    suspended — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so
    the stale write is refused rather than silently layered over a listing
    state the client never saw."

    Design: Difficulty/priority_pair_validation_conflict/temporal_pair_appeal_window_beats_nothing_but_safety_beats_referential
    """
    region = make_region(name="R10b")
    contributor = make_contributor(region["id"], display_name="C12b",
                                   email="c12b@x.com")
    listing = make_listing(region["id"], name="Bakery Ten B")
    stale_version = listing["version"]
    # A claim (not an edit) is what advances the listing version here.
    other_owner = make_contributor(region["id"], display_name="O10b",
                                   email="o10b@x.com")
    claim_listing(listing, other_owner["id"])
    current = get_listing(listing["id"])
    assert current["version"] == stale_version + 1

    resp = api.create_map_edit(
        create_map_edit_payload(
            listing_id=listing["id"], contributor_id=contributor["id"],
            edit_type="NAME", payload={"name": "BEST CHEAP Bakery Ten B"},
            expected_listing_version=stale_version,
        ),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_listing(listing["id"])
    assert after["keyword_stuffing_strikes"] == 0, (
        "the stuffing screen must not run once the stale-version check fires"
    )
