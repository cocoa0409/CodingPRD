"""Cross-reference reachability, list filtering, and RBAC denials."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appeal_case,
    create_review_ticket_payload,
    decide_case,
    make_contributor,
    make_contributor_headers,
    make_hours_observation,
    make_listing,
    make_map_edit,
    make_region,
    make_review,
    make_routing_update,
    make_verified_listing,
    start_appeal_review,
    suspend_listing,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MOD1 = TEST_USERS["moderator_headers"]

LONG_APPEAL = (
    "This appeal statement is deliberately long enough to pass the "
    "fifty character minimum length requirement."
)


def test_fk_reverse_reachability_subresources(api):
    """PRD §3.4: "Edits list with `listing_id`, `contributor_id`, `status`,
    `edit_type`, and `review_ticket_id` filters; a listing's edits and the
    tickets referencing a given edit each have their own reverse-lookup
    listings."
    PRD §3.5: "Review flags are listable with `review_id`,
    `reporter_contributor_id`, `status`, and `reason` filters, and the tickets
    referencing a given flag are reachable through their own reverse listing."
    PRD §3.7: "Observations can be listed per listing with a `day_mask`
    filter."
    PRD §3.6: "The suspension response returns the newly created case, which
    can then be browsed alongside others with `listing_id`, `status`, and
    `violation_type` filters, or per listing through the reverse lookup."

    Design: Corner/endpoints/fk_reverse_reachability_subresources
    """
    region = make_region(name="RFK")
    contributor = make_contributor(region["id"], display_name="CFK",
                                   email="fk@x.com")
    listing = make_listing(region["id"], name="FK Biz")
    edit = make_map_edit(listing, contributor["id"])
    make_review(listing["id"], contributor["id"], rating=5,
                text="Great spot, friendly staff and quick service.")
    make_hours_observation(listing["id"], "WEB_CRAWL", day_mask="1111100",
                           open_time="09:00", close_time="17:00")

    edits, _ = validate_paginated(api.list_listing_map_edits(listing["id"], ADMIN))
    assert len(edits) == 1 and edits[0]["id"] == edit["id"]

    reviews, _ = validate_paginated(api.list_listing_reviews(listing["id"], ADMIN))
    assert len(reviews) == 1

    hours, _ = validate_paginated(
        api.list_listing_hours_observations(listing["id"], ADMIN)
    )
    assert len(hours) == 1

    cases, _ = validate_paginated(
        api.list_listing_suspension_cases(listing["id"], ADMIN)
    )
    assert cases == [], "typed empty array, not an error"

    tickets, _ = validate_paginated(
        api.list_map_edit_review_tickets(edit["id"], MOD1)
    )
    assert tickets == [], "unassigned edit has no referencing tickets"


def test_permanent_closure_excluded_from_default_list(api):
    """PRD §3.2: "Listings can be listed with filters on `region_id`,
    `owner_contributor_id`, `status`, `visibility`, and `category`;
    permanently closed listings are excluded from list results unless the
    caller explicitly filters for the `PERMANENTLY_CLOSED` status."

    Design: Corner/endpoints/permanent_closure_excluded_from_default_list
    """
    region = make_region(name="RPC2")
    owner = make_contributor(region["id"], display_name="OwnPC2", email="pc@x.com")
    make_listing(region["id"], name="Alive", address_text="16 Main St")
    dead, _ = make_verified_listing(region["id"], owner["id"], name="Dead",
                                    method="RECORDS")
    case = suspend_listing(dead["id"], analyst_id="pa-1",
                           violation_type="FAKE_REVIEWS",
                           evidence_notes="review ring")
    appeal_case(case["id"], owner["id"], appeal_text=LONG_APPEAL)
    start_appeal_review(case["id"], analyst_id="pa-2")
    decide_case(case["id"], analyst_id="pa-2", decision="UPHELD")

    default, meta = validate_paginated(api.list_listings(ADMIN))
    ids = [l["id"] for l in default]
    assert len(default) == 1, f"default list excludes closed, got {len(default)}"
    assert dead["id"] not in ids

    filtered, _ = validate_paginated(
        api.list_listings(ADMIN, params={"status": "PERMANENTLY_CLOSED"})
    )
    assert [l["id"] for l in filtered] == [dead["id"]]


def test_contributor_cannot_suspend_or_resolve(api):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Role segregation is strict. Only a `Moderator` may create,
    claim, resolve, or escalate review tickets and dismiss review flags; a
    `Contributor` cannot resolve tickets, and a `Moderator` cannot suspend
    listings. Only a `PolicyAnalyst` may suspend a listing, force
    re-verification, revert a published edit, or take an appeal under review
    and decide it."

    Design: Corner/roles/contributor_cannot_suspend_or_resolve
    """
    region = make_region(name="RRBAC")
    contributor = make_contributor(region["id"], display_name="CRBAC",
                                   email="rbac@x.com")
    listing = make_listing(region["id"], name="RBAC Biz")

    resp = api.suspend_listing(
        listing["id"],
        {"violation_type": "IMPERSONATION",
         "evidence_notes": "contributor-forged suspend"},
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    resp = api.create_review_ticket(
        create_review_ticket_payload(queue="EDIT_REVIEW"),
        make_contributor_headers(contributor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing `X-User-Role`, carrying a role string
    outside the declared set, or missing `X-User-ID` for any role other than
    `Anonymous` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/missing_auth_headers_unauthenticated
    """
    resp = api._request("GET", "/v1/regions", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_imagery_operator_cannot_validate_routing(api):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Only a `RoutingEngineer` may validate, activate, or cancel
    routing updates."

    Design: Corner/roles/imagery_operator_cannot_validate_routing
    """
    region = make_region(name="RRBAC2")
    update = make_routing_update(region, segment_ref="S20", kind="CLOSURE",
                                 effective_start="2026-10-01T00:00:00Z",
                                 effective_end="2026-10-02T00:00:00Z")

    resp = api.validate_routing_update(
        update["id"], TEST_USERS["imagery_operator_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    read = validate_success(api.get_routing_update(update["id"], ADMIN))
    assert read["status"] == "PROPOSED"
