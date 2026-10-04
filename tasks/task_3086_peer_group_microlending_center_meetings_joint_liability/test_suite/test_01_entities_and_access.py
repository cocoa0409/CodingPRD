"""Branch/entity corners and request-context access control.

Covers corner-design instances in the entities (Creation, Listing, Not Found,
Required Fields, Type Constraints, Immutability, Parent Relationships) and
rbac sections.
"""
import requests

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_application,
    assert_branch,
    create_branch,
    create_branch_payload,
    create_center_manager_payload,
    create_center_payload,
    create_member_payload,
    disburse_member,
    get_success_data,
    make_center_manager_headers,
    make_member_headers,
    recruit_member,
    setup_active_group,
    setup_open_meeting_with_loan,
    setup_org,
    submit_application,
    draft_application,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
FO = TEST_USERS["field_officer_headers"]


class TestBranchCreation:
    def test_branch_create_returns_defaults_and_system_fields(self, api):
        """PRD §3.1: "its `active_member_count` starts at zero and its `tier` is
        derived, never set: `SMALL` while the branch has fewer than 200 active
        members, `MEDIUM` from 200 up to but not including 500, and `LARGE` at
        500 or more."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/branch_create_returns_defaults_and_system_fields
        """
        body = api.create_branch(create_branch_payload(), PA)
        assert body.status_code == 201, f"Expected 201, got {body.status_code}: {body.text}"
        envelope = body.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert envelope["meta"]["api_request_timestamp"]
        branch = validate_success(body, expected_status=201)
        assert_branch(branch)
        assert branch["tier"] == "SMALL", f"new branch tier must be SMALL, got {branch['tier']}"
        assert branch["active_member_count"] == 0
        assert branch["total_manager_caseload"] == 0
        assert branch["version"] == 1


class TestMemberListing:
    def test_member_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "`limit` caps the number of returned items; it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` skips that many
        items before returning results and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/member_list_paginates_with_total_count_and_has_more
        """
        branch = create_branch()
        for _ in range(3):
            recruit_member(branch["id"])

        page1 = api.list_members(
            PA, params={"branch_id": branch["id"], "status": "RECRUITED", "limit": 2, "offset": 0}
        )
        rows1, meta1 = validate_paginated(page1)
        assert len(rows1) == 2, f"limit=2 must return 2 rows, got {len(rows1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = api.list_members(
            PA, params={"branch_id": branch["id"], "status": "RECRUITED", "limit": 2, "offset": 2}
        )
        rows2, meta2 = validate_paginated(page2)
        assert len(rows2) == 1, f"offset=2 must return the remaining 1 row, got {len(rows2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        unfiltered = api.list_members(PA, params={"branch_id": branch["id"]})
        rows3, meta3 = validate_paginated(unfiltered)
        assert len(rows3) == 3
        assert meta3["limit"] == 10, f"default limit is 10, got {meta3['limit']}"
        assert meta3["offset"] == 0, f"default offset is 0, got {meta3['offset']}"

    def test_member_get_with_unknown_id_returns_member_not_found(self, api):
        """PRD §2.9: "Wherever a path does contain an identifier, identifiers
        are validated left to right, and the request fails immediately with the
        `404` error of the first identifier that does not resolve". The
        per-type errors include `ERR_MEMBER_NOT_FOUND`.

        Design: Corner/entities/member_get_with_unknown_id_returns_member_not_found
        """
        response = api.get_member("3f6b2a1c-9e8d-4c7b-a5f4-1d2e3c4b5a69", PA)
        validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND, expected_status=404)


class TestMemberCreationRules:
    def test_member_create_missing_national_id_returns_invalid_request(self, api):
        """PRD §2.8: "Malformed payloads — a missing required field, a type
        mismatch, an unknown enum value, a duplicated `national_id`, or a
        `requested_amount_cents` that is not a positive multiple of 100 — are
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/member_create_missing_national_id_returns_invalid_request
        """
        branch = create_branch()
        response = api.create_member(
            {"branch_id": branch["id"], "full_name": "No Id"}, FO
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        rows, meta = validate_paginated(
            api.list_members(PA, params={"branch_id": branch["id"]})
        )
        assert meta["total_count"] == 0, "no member may be created by the rejected call"

    def test_member_create_duplicate_national_id_returns_invalid_request(self, api):
        """PRD §3.2: "the national id is a government identifier that must be
        globally unique across all members, and a duplicate is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/member_create_duplicate_national_id_returns_invalid_request
        """
        branch_a = create_branch()
        branch_b = create_branch()
        first = recruit_member(branch_a["id"], national_id="NID-DUP-1")
        response = api.create_member(
            create_member_payload(branch_b["id"], national_id=first["national_id"]), FO
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestAppendOnlyRecords:
    def test_consensus_vote_has_no_version_field(self, api):
        """PRD §2.5: "Three record types are append-only audit records and
        carry only `id` and `created_at` — both `updated_at` and `version` are
        absent from them: consensus votes (a `decision` cast against a
        `loan_application_id` by a `voter_member_id`), meeting attendance rows
        (a `present` flag joining a `center_meeting_id` to a `member_id`), and
        credit bureau reports".

        Design: Corner/entities/consensus_vote_has_no_version_field
        """
        ctx = setup_active_group(prefix="vote-fields")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        voter = ctx["peers"][0]
        response = api.cast_vote(
            application["id"], {"decision": "APPROVE"}, make_member_headers(voter["id"])
        )
        vote = validate_success(response, expected_status=201)
        assert vote["id"], "vote must carry an id"
        assert vote["created_at"], "vote must carry created_at"
        assert "version" not in vote, "append-only vote must not carry version"
        assert "updated_at" not in vote, "append-only vote must not carry updated_at"


class TestSavingsAccountReverseLookup:
    def test_savings_account_reverse_lookup_before_first_disbursement_is_empty(self, api):
        """PRD §3.8: "Every borrower carries exactly one savings account, opened
        automatically at their first disbursement in `OPEN` status; reading a
        member's account yields an array of zero or one accounts".

        Design: Corner/entities/savings_account_reverse_lookup_before_first_disbursement_is_empty
        """
        branch = create_branch()
        member = recruit_member(branch["id"])
        response = api.get_member_savings_account(member["id"], PA)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert rows == [], "a member with no disbursement has no savings account"
        assert meta["total_count"] == 0


class TestRbacDenials:
    def test_field_officer_cannot_disburse(self, api):
        """PRD §2.10: "a `FieldOfficer` recruits members, builds groups, and
        files applications but can never collect a repayment, disburse a loan,
        or void a transaction; disbursement, reconciliation, voids, and
        restructuring belong to the `BranchManager`".

        Design: Corner/rbac/field_officer_cannot_disburse
        """
        ctx = setup_active_group(prefix="fo-disburse")
        application = draft_application(ctx["group"]["id"], ctx["applicant"]["id"])
        submit_application(application["id"])
        approve_application(
            application["id"], ctx["applicant"]["id"], [p["id"] for p in ctx["peers"]]
        )
        response = api.disburse_loan_application(application["id"], FO)
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        current = get_success_data(api.get_loan_application(application["id"], PA))
        assert current["status"] == "APPROVED", "a denied disburse must leave no side effects"

    def test_center_manager_cannot_reconcile_or_void(self, api):
        """PRD §2.1: "a `CenterManager` may never reconcile, void, or disburse".

        Design: Corner/rbac/center_manager_cannot_reconcile_or_void
        """
        ctx = setup_open_meeting_with_loan(prefix="cm-denied")
        cm_headers = make_center_manager_headers(ctx["manager"]["id"])
        txn = get_success_data(
            api.post_collection(
                ctx["meeting"]["id"],
                {
                    "member_id": ctx["applicant"]["id"],
                    "loan_id": ctx["loan"]["id"],
                    "amount_cents": 4801,
                },
                cm_headers,
            )
        )
        get_success_data(api.close_meeting(ctx["meeting"]["id"], cm_headers))
        reconcile = api.reconcile_meeting(
            ctx["meeting"]["id"], {"declared_cash_cents": 4801}, cm_headers
        )
        validate_error(reconcile, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        void = api.void_repayment_transaction(txn["id"], cm_headers)
        validate_error(void, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        meeting = get_success_data(api.get_center_meeting(ctx["meeting"]["id"], PA))
        assert meeting["settlement_status"] == "POSTED"
        txn_now = get_success_data(api.get_repayment_transaction(txn["id"], PA))
        assert txn_now["status"] == "POSTED"

    def test_member_cannot_access_staff_write_surface(self, api):
        """PRD §2.10: "a `Member` votes and manages only their own savings;
        every staff endpoint refuses them."

        Design: Corner/rbac/member_cannot_access_staff_write_surface
        """
        branch, manager, center = setup_org()
        borrower = recruit_member(branch["id"])
        borrower_headers = make_member_headers(borrower["id"])
        create_attempt = api.create_member(
            create_member_payload(branch["id"], full_name="Sneaky", national_id="NID-SNEAKY"),
            borrower_headers,
        )
        validate_error(create_attempt, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        clock_attempt = api.set_clock("2026-09-02T00:00:00Z", borrower_headers)
        validate_error(clock_attempt, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_missing_headers_return_400_before_role_check(self, api):
        """PRD §2.8: "1. **Header presence** — missing or empty `X-User-ID` /
        `X-User-Role` fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
        2. **Role permission** — a role not entitled to the endpoint fails with
        `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/missing_headers_return_400_before_role_check
        """
        response = requests.post(
            f"{api.base_url}/branches",
            json={"name": "No Auth"},
            headers={"Content-Type": "application/json"},
        )
        validate_error(
            response,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )
