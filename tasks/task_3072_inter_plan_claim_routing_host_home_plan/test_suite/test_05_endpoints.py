"""Endpoint-level behaviors: authentication, validation failure, retrieval by FK, and error paths."""

from test_helpers import (
    ApiClient,
    create_licensed_plan,
    create_member,
    create_plan,
    get_success_data,
    set_clock,
    setup_two_plan_world,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    ASSOCIATION_ADMIN_HEADERS,
    make_home_plan_operator_headers,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api: ApiClient):
        """PRD §2.1: "A request missing either header, or carrying a role string not among these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/endpoints/missing_auth_headers_returns_unauthenticated
        """
        set_clock(api)
        res = api.create_plan(f.plan_payload(), headers={})
        validate_error(res, "ERR_UNAUTHENTICATED", 401)

    def test_missing_role_header_returns_unauthenticated(self, api: ApiClient):
        """PRD §2.1: "A request missing either header, or carrying a role string not among these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/endpoints/missing_auth_headers_returns_unauthenticated
        """
        set_clock(api)
        res = api.create_plan(f.plan_payload(), headers={"X-User-ID": "someone"})
        validate_error(res, "ERR_UNAUTHENTICATED", 401)


class TestRequestShapeValidation:
    def test_create_plan_missing_plan_code_returns_validation_failed(self, api: ApiClient):
        """PRD §2.8: "A malformed request body — a missing required field, a wrong type, or an unparseable value — is the lowest-priority failure and surfaces as `ERR_VALIDATION_FAILED` (HTTP 400) only when no earlier check has failed."

        Design: Corner/endpoints/create_plan_missing_plan_code_returns_validation_failed
        """
        set_clock(api)
        res = api.create_plan(
            {"legal_name": "No Code Plan", "service_area_states": ["CA"]},
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_VALIDATION_FAILED", 400)

    def test_create_plan_missing_legal_name_returns_validation_failed(self, api: ApiClient):
        """PRD §2.8: "A malformed request body — a missing required field, a wrong type, or an unparseable value — is the lowest-priority failure and surfaces as `ERR_VALIDATION_FAILED` (HTTP 400) only when no earlier check has failed."

        Design: Corner/endpoints/create_plan_missing_plan_code_returns_validation_failed
        """
        set_clock(api)
        res = api.create_plan(
            {"plan_code": "HCA", "service_area_states": ["CA"]},
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_VALIDATION_FAILED", 400)


class TestClaimListByMember:
    def test_claims_list_fk_reverse_reachability_by_member(self, api: ApiClient):
        """PRD §3.6: "Claims are listed with optional `home_plan_id`, `host_plan_id`, `member_id`, `national_account_id`, and `status` filters"

        Design: Corner/endpoints/claims_list_fk_reverse_reachability_by_member
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        member2 = get_success_data(
            api.create_member(f.member_payload(world["home"]["id"], member_number="M2", full_name="Pat Two"), world["home_headers"])
        )
        get_success_data(
            api.create_claim(f.claim_payload(world["member"]["id"], world["host"]["id"]), world["host_headers"])
        )
        c2 = get_success_data(
            api.create_claim(
                f.claim_payload(member2["id"], world["host"]["id"], service_date="2026-08-11"),
                world["host_headers"],
            )
        )
        data, meta = validate_paginated(api.list_claims(world["host_headers"], params={"member_id": member2["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == c2["id"]

    def test_claims_list_by_other_member_excludes_unrelated(self, api: ApiClient):
        """PRD §3.6: "Claims are listed with optional `home_plan_id`, `host_plan_id`, `member_id`, `national_account_id`, and `status` filters"

        Design: Corner/endpoints/claims_list_fk_reverse_reachability_by_member
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        member2 = get_success_data(
            api.create_member(f.member_payload(world["home"]["id"], member_number="M2", full_name="Pat Two"), world["home_headers"])
        )
        c1 = get_success_data(
            api.create_claim(f.claim_payload(world["member"]["id"], world["host"]["id"]), world["host_headers"])
        )
        get_success_data(
            api.create_claim(
                f.claim_payload(member2["id"], world["host"]["id"], service_date="2026-08-11"),
                world["host_headers"],
            )
        )
        data, meta = validate_paginated(api.list_claims(world["host_headers"], params={"member_id": world["member"]["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == c1["id"]


class TestEligibilityAnswerUnknownMember:
    def test_answer_for_unknown_member_rejected(self, api: ApiClient):
        """PRD §3.2: "Answering the inquiry succeeds only when a member with the inquired `member_number` exists under that home plan — when no such member exists, the answer attempt fails with `ERR_MEMBER_NOT_FOUND` (HTTP 404), and the inquiry's only remaining path is rejection, moving it from `ROUTED` to `REJECTED`."

        Design: Corner/errors/eligibility_answer_for_unknown_member_rejected
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        inquiry = get_success_data(
            api.create_eligibility_inquiry(
                f.eligibility_inquiry_payload(world["host"]["id"], world["home"]["id"], member_number="GHOST"),
                world["host_headers"],
            )
        )
        res = api.answer_eligibility_inquiry(inquiry["id"], world["home_headers"])
        validate_error(res, "ERR_MEMBER_NOT_FOUND", 404)

    def test_unknown_member_inquiry_can_still_be_rejected(self, api: ApiClient):
        """PRD §3.2: "when no such member exists, the answer attempt fails with `ERR_MEMBER_NOT_FOUND` (HTTP 404), and the inquiry's only remaining path is rejection, moving it from `ROUTED` to `REJECTED`."

        Design: Corner/errors/eligibility_answer_for_unknown_member_rejected
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        inquiry = get_success_data(
            api.create_eligibility_inquiry(
                f.eligibility_inquiry_payload(world["host"]["id"], world["home"]["id"], member_number="GHOST"),
                world["host_headers"],
            )
        )
        rejected = validate_success(api.reject_eligibility_inquiry(inquiry["id"], world["home_headers"]), 200)
        assert rejected["status"] == "REJECTED"


class TestDuplicatePlanCode:
    def test_duplicate_plan_code_rejected(self, api: ApiClient):
        """PRD §3.1: "a `plan_code` (a short licensee code such as BCBSTX, unique across all plans — a duplicate registration is rejected with `ERR_DUPLICATE_PLAN_CODE`)"

        Design: Corner/errors/duplicate_plan_code_rejected
        """
        set_clock(api)
        create_plan(api, plan_code="HCA", service_area_states=["CA"])
        res = api.create_plan(
            f.plan_payload(plan_code="HCA", legal_name="Another Plan", service_area_states=["NV"]),
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_DUPLICATE_PLAN_CODE", 409)

    def test_distinct_plan_codes_accepted(self, api: ApiClient):
        """PRD §3.1: "a `plan_code` (a short licensee code such as BCBSTX, unique across all plans — a duplicate registration is rejected with `ERR_DUPLICATE_PLAN_CODE`)"

        Design: Corner/errors/duplicate_plan_code_rejected
        """
        set_clock(api)
        create_plan(api, plan_code="HCA", service_area_states=["CA"])
        ok = validate_success(
            api.create_plan(f.plan_payload(plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"]), ASSOCIATION_ADMIN_HEADERS),
            201,
        )
        assert ok["plan_code"] == "TTX"
