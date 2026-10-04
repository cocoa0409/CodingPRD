"""Employer and member loading: creation contract, dependents, pagination,
and eligibility-file uniqueness."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_employer_payload, create_member_payload,
    set_clock, setup_employer,
)


class TestEmployerCreation:
    def test_employer_create_returns_all_declared_fields_and_version_one(
            self, api, platform_admin_headers):
        """PRD §2.5: "Every persisted top-level resource — Employer, Member,
        CoverageWindow, Provider, QualitySnapshot, ConsentGrant, NavigationCase,
        Appointment, RecordRequest, ExpertOpinionCase, OpinionRecordItem, Claim,
        BillingCase, PlanAuthorization — carries four system-managed fields: `id`,
        a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits; `updated_at`, refreshed on every
        mutation; and `version`, an integer incremented on every mutation."
        PRD §4: "Operations that create a new resource return `201 Created`".

        Design: Corner/entities/employer_create_returns_all_declared_fields_and_version_one
        """
        set_clock()
        resp = api.create_employer(
            create_employer_payload(
                name="Umbrella Corp", pepm_fee_cents=1750,
                avg_in_out_cost_delta_cents=275000, emo_benefit_enabled=True),
            platform_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["name"] == "Umbrella Corp"
        assert data["pepm_fee_cents"] == 1750
        assert data["avg_in_out_cost_delta_cents"] == 275000
        assert data["emo_benefit_enabled"] is True
        assert data["version"] == 1
        assert data["id"]
        assert data["created_at"]
        assert data["updated_at"]


class TestMemberDependents:
    def test_member_create_with_dependent_links_to_subscriber(
            self, api, platform_admin_headers):
        """PRD §3.1: "A dependent — any member whose `relationship` is not
        `SELF` — must additionally carry `subscriber_id` naming the subscriber
        member they belong to; a `SELF` member carries none."
        PRD §3.1: "a member's dependents can be listed via the subscriber
        relationship."

        Design: Corner/entities/member_create_with_dependent_links_to_subscriber
        """
        set_clock()
        emp = setup_employer()
        subscriber = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Dana White", external_member_ref="V-1"),
            platform_admin_headers), expected_status=201)
        assert subscriber.get("subscriber_id") is None

        dependent = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Kiddo White", relationship="CHILD",
                subscriber_id=subscriber["id"], external_member_ref="V-2"),
            platform_admin_headers), expected_status=201)
        assert dependent["subscriber_id"] == subscriber["id"]
        assert dependent["relationship"] == "CHILD"

        data, meta = validate_paginated(api.list_dependents(
            subscriber["id"], platform_admin_headers))
        assert len(data) == 1
        assert data[0]["id"] == dependent["id"]

    def test_dependent_create_without_subscriber_id_rejected(
            self, api, platform_admin_headers):
        """PRD §3.1: "Supplying a dependent without a subscriber, or a
        `CLINICAL` intake without `acuity`, or a `COST` intake without
        `estimated_cost_cents`, or a denial without `denial_reason`, are all
        malformed requests rejected with `ERR_INVALID_REQUEST` (400)".

        Design: Corner/entities/dependent_create_without_subscriber_id_rejected
        """
        set_clock()
        emp = setup_employer()
        payload = create_member_payload(
            full_name="Orphan Dep", relationship="CHILD",
            external_member_ref="W-9")
        resp = api.create_member(emp["id"], payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestMemberLookup:
    def test_member_get_unknown_id_returns_not_found(
            self, api, platform_admin_headers):
        """PRD §2.6: "Fourth, reference resolution: every identifier in the
        path and body must resolve to an existing resource, validated left to
        right — for example, a request naming an employer and a member under it
        rejects with `ERR_NOT_FOUND` (404) on the employer before the member is
        even looked up."

        Design: Corner/entities/member_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_member(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestMemberListPagination:
    def test_members_list_pagination_envelope(
            self, api, platform_admin_headers, employer_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items and defaults to 0."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/members_list_pagination_envelope
        """
        set_clock()
        emp = setup_employer()
        for i in range(3):
            validate_success(api.create_member(
                emp["id"], create_member_payload(
                    full_name=f"M {i + 1}", external_member_ref=f"P-{i + 1}"),
                platform_admin_headers), expected_status=201)

        data, meta = validate_paginated(api.list_employer_members(
            emp["id"], employer_admin_headers, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(api.list_employer_members(
            emp["id"], employer_admin_headers, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        data3, meta3 = validate_paginated(api.list_employer_members(
            emp["id"], employer_admin_headers))
        assert len(data3) == 3
        assert meta3["limit"] == 10
        assert meta3["offset"] == 0


class TestDuplicateMemberRef:
    def test_duplicate_member_ref_within_employer_rejected(
            self, api, platform_admin_headers):
        """PRD §3.1: "The `external_member_ref` must be unique within the
        employer; a duplicate load is rejected with `ERR_DUPLICATE_MEMBER_REF`
        (409)."

        Design: Corner/validations/duplicate_member_ref_within_employer_rejected
        """
        set_clock()
        e1 = setup_employer(name="E1")
        e2 = setup_employer(name="E2")
        validate_success(api.create_member(
            e1["id"], create_member_payload(external_member_ref="DUP-1"),
            platform_admin_headers), expected_status=201)

        dup = api.create_member(
            e1["id"], create_member_payload(
                full_name="Second", external_member_ref="DUP-1"),
            platform_admin_headers)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_MEMBER_REF,
                       expected_status=409)

        cross = api.create_member(
            e2["id"], create_member_payload(
                full_name="CrossTenant", external_member_ref="DUP-1"),
            platform_admin_headers)
        validate_success(cross, expected_status=201)
