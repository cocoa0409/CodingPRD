"""Role admission, authentication, ownership and the segregation of duties."""
from test_helpers import (
    ADMIN_USER_ID,
    ANALYST_USER_ID,
    CLOCK_CORRECTION_DEADLINE,
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    OTHER_ANALYST_USER_ID,
    REVIEWER_USER_ID,
    assert_instant,
    assert_score,
    create_appeal_payload,
    create_correction_request_payload,
    create_filing_record_payload,
    create_organization,
    create_organization_payload,
    decide_appeal_payload,
    headers_for_role,
    make_organization_rep_headers,
    make_panelist_headers,
    make_reviewer_headers,
    organization_version,
    publish_payload,
    read_cycle,
    set_clock,
    set_clock_payload,
    setup_published_cycle,
    setup_scored_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

# The two extra fiscal years the shared write exercises, whose expense
# components satisfy the identity of admission check 29.
FILING_FY2022 = {
    "total_expense_cents": 3000000,
    "program_expense_cents": 2000000,
    "fundraising_expense_cents": 600000,
    "admin_expense_cents": 400000,
    "contributions_cents": 2500000,
    "total_revenue_cents": 3200000,
    "net_assets_cents": 1500000,
    "total_liabilities_cents": 500000,
}
FILING_FY2021 = {
    "total_expense_cents": 2000000,
    "program_expense_cents": 1400000,
    "fundraising_expense_cents": 400000,
    "admin_expense_cents": 200000,
    "contributions_cents": 1800000,
    "total_revenue_cents": 2100000,
    "net_assets_cents": 900000,
    "total_liabilities_cents": 300000,
}


def test_every_roles_exclusive_operation_is_refused_to_the_other_five(
    api, admin_headers, analyst_headers, reviewer_headers, public_headers
):
    """Each denial names the role most plausibly entitled to the operation, and
    every path identifier is deliberately absent, so a refused caller learns
    nothing about which rows exist.

    PRD §2.8: "**Role admission.** `X-User-Role` is one of the six declared roles and is among the roles the target endpoint admits, on every endpoint, else `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.8: "Because role admission (2) precedes path existence (3), a caller with the wrong role never learns whether a resource exists."

    PRD §4: "The `Authorized Role(s)` column is the sole input to the role check at priority 2 of §2.8; ownership, segregation-of-duties, assigned-analyst and panel-membership restrictions apply on top of it and are described in §2.1, §2.10 and §3."

    PRD §2.5: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to the host's wall-clock time under any circumstance."

    Design: Corner/rbac/every_roles_exclusive_operation_is_refused_to_the_other_five
    """
    validate_error(
        api.score_rating_cycle(NON_EXISTENT_UUID, admin_headers),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.publish_rating_cycle(
            NON_EXISTENT_UUID, publish_payload("I scored it, I can ship it"), analyst_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.decide_appeal(
            NON_EXISTENT_UUID,
            decide_appeal_payload(
                "DENY", decision_note="Seating the panel is not deciding it"
            ),
            admin_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_organization(
            create_organization_payload(
                legal_name="Analyst Registered Trust",
                ein="333333333",
                contact_email="ops@art.org",
            ),
            analyst_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.set_clock(set_clock_payload("2027-01-01T00:00:00Z"), reviewer_headers),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_correction_request(
            create_correction_request_payload(
                NON_EXISTENT_UUID,
                narrative="An analyst filing the organization's own dispute",
            ),
            analyst_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.create_appeal(
            create_appeal_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                grounds="A donor appealing on the charity's behalf",
            ),
            public_headers,
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.list_governance_profiles(public_headers), "ERR_ROLE_NOT_PERMITTED", 403
    )

    rows, meta = validate_paginated(api.list_organizations(admin_headers))
    assert rows == []
    assert meta["total_count"] == 0

    # A stored `*_at` reads the logical clock, so a fresh row is the observation
    # that the refused clock request moved nothing.
    organization = validate_success(
        api.create_organization(create_organization_payload(), admin_headers), 201
    )
    assert_instant(organization["created_at"], CLOCK_EPOCH, "created_at")


def test_shared_reads_return_the_identical_row_to_every_role_that_declares_them(
    api, admin_headers, analyst_headers, reviewer_headers, public_headers
):
    """The widest shared read answers all six roles with one byte-identical row,
    and the one shared write admits the analyst and the charity alike while
    still serialising them through the organization's version counter.

    PRD §4: "Returns one rating cycle with both the provisional and the final score family. | `MethodologyAdmin`, `RatingAnalyst`, `PublishingReviewer`, `AppealPanelist`, `OrganizationRep`, `PublicUser`"

    PRD §4: "The `Authorized Role(s)` column is the sole input to the role check at priority 2 of §2.8; ownership, segregation-of-duties, assigned-analyst and panel-membership restrictions apply on top of it and are described in §2.1, §2.10 and §3."

    PRD §3.3: "Either a `RatingAnalyst` or the charity's own `OrganizationRep` submits one, naming the `organization_id` it describes, the `fiscal_year` it covers as an integer between 2000 and 2100, and a `source_kind` of `AUDITED_STATEMENT`, `PUBLIC_FILING` or `ORG_SUBMISSION`."

    PRD §3.3: "`origin` records how the row arrived: `ORG_PORTAL` when the submitter was an `OrganizationRep`, `ANALYST_ENTRY` when it was a `RatingAnalyst`, and `CORRECTION_APPLIED` for the replacement rows the correction and appeal machinery synthesizes."

    PRD §2.7: "If that value does not equal the organization's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412) and no filing row is written."

    Design: Corner/rbac/shared_reads_return_the_identical_row_to_every_role_that_declares_them
    """
    scenario = setup_published_cycle()
    cycle_id = scenario["cycle"]["id"]
    organization_id = scenario["organization"]["id"]
    org_rep_headers = make_organization_rep_headers(organization_id)

    readers = {
        "MethodologyAdmin": admin_headers,
        "RatingAnalyst": analyst_headers,
        "PublishingReviewer": reviewer_headers,
        "AppealPanelist": make_panelist_headers("panel-a"),
        "OrganizationRep": org_rep_headers,
        "PublicUser": public_headers,
    }
    bodies = {
        role: validate_success(api.get_rating_cycle(cycle_id, headers))
        for role, headers in readers.items()
    }

    reference = bodies["MethodologyAdmin"]
    assert reference["status"] == "PUBLISHED"
    assert_score(reference["final_composite_score"], 83.13, "final_composite_score")
    assert reference["assigned_analyst_user_id"] == ANALYST_USER_ID
    assert reference["publishing_reviewer_user_id"] == REVIEWER_USER_ID
    for role, body in bodies.items():
        assert body == reference, f"{role} was handed a different rating cycle row"
        assert body["version"] == reference["version"], f"{role} moved the version"

    trend = validate_success(api.get_rating_trend(organization_id, public_headers))
    assert_score(trend["latest_published_score"], 83.13, "latest_published_score")

    version = organization_version(organization_id)
    by_analyst = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization_id,
                version,
                fiscal_year=2022,
                source_kind="PUBLIC_FILING",
                **FILING_FY2022,
            ),
            analyst_headers,
        ),
        201,
    )
    assert by_analyst["status"] == "RECEIVED"
    assert by_analyst["origin"] == "ANALYST_ENTRY"
    assert by_analyst["source_precedence"] == 2

    # The analyst's submission already advanced the organization, so the version
    # the charity is still holding is stale.
    validate_error(
        api.create_filing_record(
            create_filing_record_payload(
                organization_id,
                version,
                fiscal_year=2021,
                source_kind="PUBLIC_FILING",
                **FILING_FY2021,
            ),
            org_rep_headers,
        ),
        "ERR_STALE_VERSION",
        412,
    )

    refreshed = organization_version(organization_id)
    assert refreshed == version + 1
    by_org = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization_id,
                refreshed,
                fiscal_year=2021,
                source_kind="PUBLIC_FILING",
                **FILING_FY2021,
            ),
            org_rep_headers,
        ),
        201,
    )
    assert by_org["status"] == "RECEIVED"
    assert by_org["origin"] == "ORG_PORTAL"
    assert organization_version(organization_id) == refreshed + 1


def test_an_empty_identity_header_is_rejected_before_the_role_is_even_considered(
    api, admin_headers
):
    """An empty user id and an empty role are both authentication failures at
    priority 1, while a syntactically fine role that is not one of the six is
    the only one of the three that reaches the role gate.

    PRD §2.8: "**Authentication.** `X-User-ID` and `X-User-Role` are both present and non-empty, on every endpoint without exception, else `ERR_UNAUTHENTICATED` (401)."

    PRD §2.8: "**Role admission.** `X-User-Role` is one of the six declared roles and is among the roles the target endpoint admits, on every endpoint, else `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.8: "Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response."

    Design: Corner/rbac/an_empty_identity_header_is_rejected_before_the_role_is_even_considered
    """
    validate_error(
        api.list_organizations(headers_for_role("MethodologyAdmin", "")),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.list_organizations(headers_for_role("", ADMIN_USER_ID)),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api.list_organizations(headers_for_role("SUPER_ADMIN", ADMIN_USER_ID)),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    rows, meta = validate_paginated(api.list_organizations(admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_an_organization_rep_is_locked_to_the_organization_its_user_id_names(
    api, analyst_headers
):
    """Ownership is resolved from the identity header, through the rating cycle
    where the URL names no organization at all, and it sits below path existence
    and above the state gate.

    PRD §2.8: "**Organization ownership.** When `X-User-Role` is `OrganizationRep`, `X-User-ID` equals the `id` of the `Organization` the target resource belongs to, reached directly or through the resource's rating cycle's `organization_id`, else `ERR_NOT_RESOURCE_OWNER` (403). This check guards exactly four operations: `POST /correction-requests`, `POST /appeals`, `GET /organizations/{id}/filing-records` and `GET /organizations/{organization_id}/rating-trend`."

    PRD §2.8: "Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    PRD §4: "Ordered by fiscal_year descending then source_precedence ascending then created_at ascending, which is exactly the winning_filing_selector order."

    PRD §3.7: "the cycle must be in `ORG_REVIEW` for this to be admissible, else `ERR_CYCLE_STATE_INVALID`"

    Design: Corner/rbac/an_organization_rep_is_locked_to_the_organization_its_user_id_names
    """
    scenario = setup_scored_cycle(evaluate=False, score=False)
    organization_id = scenario["organization"]["id"]
    cycle = scenario["cycle"]
    own_headers = make_organization_rep_headers(organization_id)

    peer = create_organization(
        legal_name="Beacon Youth Alliance",
        ein="222222222",
        fiscal_year_end_month=6,
        contact_email="rep@beacon.org",
    )
    peer_headers = make_organization_rep_headers(peer["id"])

    validate_error(
        api.list_organization_filing_records(organization_id, peer_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.get_rating_trend(organization_id, peer_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.create_correction_request(
            create_correction_request_payload(
                cycle["id"],
                narrative="A competitor editing another charity's balance sheet",
            ),
            peer_headers,
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    # Ownership is reached through the cycle, so the dangling body foreign key of
    # priority 7 is never looked up at all.
    validate_error(
        api.create_appeal(
            create_appeal_payload(
                cycle["id"],
                NON_EXISTENT_UUID,
                grounds="A competitor appealing another charity's rating",
            ),
            peer_headers,
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api.list_organization_filing_records(NON_EXISTENT_UUID, peer_headers),
        "ERR_ORGANIZATION_NOT_FOUND",
        404,
    )

    peer_rows, peer_meta = validate_paginated(
        api.list_organization_filing_records(peer["id"], peer_headers)
    )
    assert peer_rows == []
    assert peer_meta["total_count"] == 0

    own_rows, own_meta = validate_paginated(
        api.list_organization_filing_records(organization_id, own_headers)
    )
    assert own_meta["total_count"] == 3
    assert [row["fiscal_year"] for row in own_rows] == [2025, 2024, 2023]
    assert own_rows[0]["id"] == scenario["filing_by_year"][2025]["id"]

    trend = validate_success(api.get_rating_trend(organization_id, own_headers))
    assert trend["latest_published_score"] is None
    assert trend["published_cycle_count"] == 0

    validate_error(
        api.create_correction_request(
            create_correction_request_payload(
                cycle["id"],
                narrative="The rated organization disputing its own net assets before review opens",
            ),
            own_headers,
        ),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )

    after = read_cycle(cycle["id"], analyst_headers)
    assert after["status"] == "DATA_COLLECTION"
    assert after["correction_round"] == 0
    _corrections, correction_meta = validate_paginated(
        api.list_correction_requests(
            analyst_headers, params={"rating_cycle_id": cycle["id"]}
        )
    )
    assert correction_meta["total_count"] == 0


def test_the_reviewer_seat_is_defined_by_the_cycles_assignment_not_by_the_persons_job(
    api, analyst_headers, other_analyst_headers
):
    """One cycle opened by analyst-1 but assigned to analyst-2: the creator is
    refused the scoring run it would have been allowed on a cycle of its own, and
    is then the one user permitted to publish it.

    PRD §2.10: "Only the analyst named in a cycle's `assigned_analyst_user_id` may score it, override its dimension points, open its organization review, or claim and decide its corrections; any other `RatingAnalyst` attempting those operations is rejected with `ERR_NOT_ASSIGNED_ANALYST`."

    PRD §2.8: "**Assigned-analyst identity.** The acting `RatingAnalyst`'s `X-User-ID` equals the cycle's `assigned_analyst_user_id`, else `ERR_NOT_ASSIGNED_ANALYST` (403). This guards five endpoints: `POST /rating-cycles/{rating_cycle_id}/score`, `POST /rating-cycles/{rating_cycle_id}/open-org-review`, `POST /rating-cycles/{rating_cycle_id}/dimension-overrides`, `POST /correction-requests/{correction_request_id}/claim` and `POST /correction-requests/{correction_request_id}/decide`."

    PRD §3.9: "The acting `X-User-ID` must differ from the cycle's `assigned_analyst_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — the reviewer may not publish a rating they themselves scored."

    PRD §2.10: "Publication is reserved to a `PublishingReviewer`, and that reviewer's `X-User-ID` must differ from the cycle's `assigned_analyst_user_id`; a reviewer who also scored the cycle is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_reviewer_seat_is_defined_by_the_cycles_assignment_not_by_the_persons_job
    """
    scenario = setup_scored_cycle(
        cycle_overrides={"assigned_analyst_user_id": OTHER_ANALYST_USER_ID},
        creator_headers=analyst_headers,
        score=False,
    )
    cycle = scenario["cycle"]
    # Creation is absent from the five endpoints the assigned-analyst check guards.
    assert cycle["assigned_analyst_user_id"] == OTHER_ANALYST_USER_ID

    validate_error(
        api.score_rating_cycle(cycle["id"], analyst_headers),
        "ERR_NOT_ASSIGNED_ANALYST",
        403,
    )
    scored = validate_success(api.score_rating_cycle(cycle["id"], other_analyst_headers))
    assert scored["status"] == "SCORED"
    assert_score(
        scored["provisional_composite_score"], 83.13, "provisional_composite_score"
    )

    validate_error(
        api.open_org_review(cycle["id"], analyst_headers),
        "ERR_NOT_ASSIGNED_ANALYST",
        403,
    )
    reviewed = validate_success(api.open_org_review(cycle["id"], other_analyst_headers))
    assert reviewed["status"] == "ORG_REVIEW"
    assert_instant(
        reviewed["correction_deadline_at"],
        CLOCK_CORRECTION_DEADLINE,
        "correction_deadline_at",
    )

    set_clock(CLOCK_CORRECTION_DEADLINE)
    before = read_cycle(cycle["id"], analyst_headers)

    validate_error(
        api.publish_rating_cycle(
            cycle["id"],
            publish_payload("The assignee signing off on itself"),
            make_reviewer_headers(OTHER_ANALYST_USER_ID),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    unmoved = read_cycle(cycle["id"], analyst_headers)
    assert unmoved["status"] == "ORG_REVIEW"
    assert unmoved["published_at"] is None
    assert unmoved["publishing_reviewer_user_id"] is None
    assert unmoved["version"] == before["version"]

    published = validate_success(
        api.publish_rating_cycle(
            cycle["id"],
            publish_payload("Cleared by a reviewer who was never the assignee"),
            make_reviewer_headers(ANALYST_USER_ID),
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["publishing_reviewer_user_id"] == ANALYST_USER_ID
    assert_score(published["final_composite_score"], 83.13, "final_composite_score")
    assert published["grade"] == "MEETS_STANDARDS"
    assert_instant(
        published["published_at"], CLOCK_CORRECTION_DEADLINE, "published_at"
    )
    assert published["version"] == before["version"] + 1
