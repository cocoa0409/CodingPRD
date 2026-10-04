"""Core API contract tests: entity creation rules, not-found, computed-field
defaults, pagination envelope, error catalogue entries, and RBAC denials.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_escrow,
    create_office,
    create_preparer,
    create_product,
    create_remediation_payload,
    create_return,
    create_return_payload,
    file_return,
    get_success_data,
    is_valid_uuid,
    make_preparer_headers,
    setup_claim_in_triage,
    setup_filed_return,
    setup_office_preparer_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestClientCreateDefaultsAndDuplicateEmail:
    def test_create_then_duplicate_email_rejected(self, api):
        """PRD §3.1: "Client registration, performed by an `OfficeManager` or
        `CaseManager` with `full_name` and `email`, enforces one email per
        client across the program: a repeat address is refused with
        `ERR_DUPLICATE_CLIENT_EMAIL` (HTTP 409)."
        PRD §2.4: "`id` — a server-minted UUID, with no type prefix."

        Design: Corner/entities/client_create_defaults_and_duplicate_email
        """
        first = validate_success(
            api.create_client({"full_name": "Client One", "email": "dup@example.com"}, OM), 201)
        assert is_valid_uuid(first["id"])
        res = api.create_client({"full_name": "Client Two", "email": "dup@example.com"}, OM)
        validate_error(res, "ERR_DUPLICATE_CLIENT_EMAIL")


class TestReturnCreateRejectsEmptyComponents:
    def test_empty_components_rejected(self, api):
        """PRD §3.2: "The array must be non-empty, drawn only from these
        codes, and free of duplicates; a violation is rejected with
        `ERR_INVALID_COMPONENTS` (HTTP 422)."

        Design: Corner/entities/return_create_rejects_empty_components
        """
        office, preparer, client = setup_office_preparer_client()
        res = api.create_return(
            create_return_payload(client["id"], office["id"], preparer["id"], components=[]), OM)
        validate_error(res, "ERR_INVALID_COMPONENTS")


class TestGetNonexistentReturnReturns404:
    def test_random_uuid_is_not_found(self, api):
        """PRD §2.9: "Every identifier appearing in a path or request body
        must resolve to an existing resource before business rules run; the
        first unresolved identifier, scanning left to right, produces
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_return_returns_404
        """
        res = api.get_return(NON_EXISTENT_UUID, OM)
        validate_error(res, "ERR_NOT_FOUND")


class TestClaimComputedFieldsIgnoreInput:
    def test_claim_born_in_triage_with_zeroed_computed_fields(self, api):
        """PRD §3.5: "The claim is born in `TRIAGE`, with `scope` and
        `error_attribution` null, all payout fields at 0, `scoped_by_user_id`
        null, and `final_liability_cents` null."

        Design: Corner/entities/claim_computed_fields_ignore_input
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        claim = ctx["claim"]
        assert claim["status"] == "TRIAGE"
        assert claim["payout_total_cents"] == 0
        assert claim["scope"] is None


class TestListPaginationEnvelope:
    def test_claims_list_pagination_meta(self, api):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100."

        After one claim intake, GET /tax/claims reports total_count 1, the
        default limit 10, and has_more false.

        Design: Corner/entities/list_pagination_envelope
        """
        setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        data, meta = validate_paginated(api.list_claims(CM))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 1


class TestAmendedReturnComponentIneligible:
    def test_amended_return_cannot_carry_product(self, api):
        """PRD §3.3: "Eligibility is strict: the return must be `FILED`, and
        it must not carry the `AMENDED_RETURN` component — a violation of
        either condition is refused with `ERR_PRODUCT_INELIGIBLE` (HTTP 422)."

        A FILED amended return (components [AMENDED_RETURN]) is refused a
        product.

        Design: Corner/calculations/amended_return_component_ineligible
        """
        office, preparer, client = setup_office_preparer_client()
        original = file_return(
            create_return(client["id"], office["id"], preparer["id"], components=["1040_SIMPLE"])["id"])
        amended = file_return(
            create_return(client["id"], office["id"], preparer["id"],
                          components=["AMENDED_RETURN"], filing_kind="AMENDED",
                          original_return_id=original["id"])["id"])
        res = api.create_product({"return_id": amended["id"], "tier": "STANDARD"}, OM)
        validate_error(res, "ERR_PRODUCT_INELIGIBLE")


class TestAmendedFilingRequiresFiledOriginal:
    def test_amended_with_preparing_original_rejected(self, api):
        """PRD §3.2: "an amended filing requires `original_return_id` pointing
        at a return that is itself already `FILED`, and is otherwise rejected
        with `ERR_AMEND_REQUIRES_ORIGINAL` (HTTP 422)."

        Design: Corner/calculations/amended_filing_requires_filed_original
        """
        office, preparer, client = setup_office_preparer_client()
        original = create_return(client["id"], office["id"], preparer["id"],
                                 components=["1040_SIMPLE"])
        assert original["status"] == "PREPARING"
        res = api.create_return(
            create_return_payload(client["id"], office["id"], preparer["id"],
                                  components=["AMENDED_RETURN"], filing_kind="AMENDED",
                                  original_return_id=original["id"]), OM)
        validate_error(res, "ERR_AMEND_REQUIRES_ORIGINAL")


class TestProductPurchaseVoidUniquenessInvariant:
    def test_duplicate_rejected_void_allows_repurchase(self, api):
        """PRD §3.3: "Exactly one `ACTIVE` product may exist per return; a
        second purchase while one is still active is rejected with
        `ERR_DUPLICATE_PRODUCT` (HTTP 409). (The conflicting purchase is
        simply refused — the existing product stays `ACTIVE`; nothing about a
        duplicate attempt moves it to `VOID`.)"
        PRD §3.3: "A successful void moves the product to `VOID` and
        increments its `version`; `VOID` is terminal."
        PRD §3.3: "The tier boundary rule is inclusive downward: a total
        exactly equal to a cap falls into the lower band."

        Purchase STANDARD, duplicate PLUS refused, void the first, then a new
        PLUS purchase succeeds at the simple-band premium.

        Design: Difficulty/compensating_invariant/product_purchase_void_uniqueness_invariant
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"])
        ret_id = ctx["tax_return"]["id"]
        prod1 = create_product(ret_id, tier="STANDARD")
        res_dup = api.create_product({"return_id": ret_id, "tier": "PLUS"}, OM)
        validate_error(res_dup, "ERR_DUPLICATE_PRODUCT")
        validate_success(api.void_product(prod1["id"], ADMIN), 200)
        prod2 = validate_success(
            api.create_product({"return_id": ret_id, "tier": "PLUS"}, OM), 201)
        assert prod2["status"] == "ACTIVE"
        assert prod2["premium_cents"] == 9900

    def test_existing_product_stays_active_on_duplicate_attempt(self, api):
        """PRD §3.3: "(The conflicting purchase is simply refused — the
        existing product stays `ACTIVE`; nothing about a duplicate attempt
        moves it to `VOID`.)"

        Design: Difficulty/compensating_invariant/product_purchase_void_uniqueness_invariant
        """
        ctx = setup_filed_return(components=["1040_SIMPLE"])
        ret_id = ctx["tax_return"]["id"]
        prod1 = create_product(ret_id, tier="STANDARD")
        validate_error(api.create_product({"return_id": ret_id, "tier": "PLUS"}, OM),
                       "ERR_DUPLICATE_PRODUCT")
        products, meta = validate_paginated(api.list_return_products(ret_id, CM))
        assert len(products) == 1
        assert products[0]["id"] == prod1["id"]
        assert products[0]["status"] == "ACTIVE"


class TestProductVoidBlockedByOpenClaim:
    def test_void_with_triage_claim_rejected(self, api):
        """PRD §3.3: "A `ProgramAdmin` may void an `ACTIVE` product, but only
        while no claim referencing it sits in any non-terminal status — a
        claim in `TRIAGE`, `INFO_NEEDED`, `SCOPE_CONFIRMED`, `ASSIGNED`,
        `REPRESENTING`, or `REOPENED` blocks the void with
        `ERR_VOID_CLAIMS_OPEN` (HTTP 409)."

        Design: Corner/validations/product_void_blocked_by_open_claim
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        res = api.void_product(ctx["product"]["id"], ADMIN)
        validate_error(res, "ERR_VOID_CLAIMS_OPEN")
        products, _meta = validate_paginated(api.list_return_products(ctx["tax_return"]["id"], CM))
        assert products[0]["status"] == "ACTIVE"


class TestDuplicateEscrowRejected:
    def test_second_escrow_for_office_rejected(self, api):
        """PRD §3.1: "Program funding lives in exactly one `OfficeEscrow` per
        office, created by a `ProgramAdmin` with the `office_id` and a
        strictly positive `funded_cents`. Attempting to fund a second escrow
        for the same office fails with `ERR_DUPLICATE_ESCROW` (HTTP 409)."

        Design: Corner/errors/duplicate_escrow_rejected
        """
        office = create_office()
        create_escrow(office["id"], funded_cents=1_000_000)
        res = api.create_escrow({"office_id": office["id"], "funded_cents": 2_000_000}, ADMIN)
        validate_error(res, "ERR_DUPLICATE_ESCROW")


class TestDowngradeForbidden:
    def test_master_to_senior_rejected(self, api):
        """PRD §3.1: "A preparer may later be upgraded to a strictly
        higher-multiplier tier by an `OfficeManager`; attempting a lateral or
        downward move is rejected with `ERR_DOWNGRADE_FORBIDDEN` (HTTP 422)".

        Design: Corner/errors/downgrade_forbidden
        """
        office = create_office()
        preparer = create_preparer(office["id"], tier="MASTER")
        res = api.upgrade_preparer(preparer["id"], {"tier": "SENIOR"}, OM)
        validate_error(res, "ERR_DOWNGRADE_FORBIDDEN")
        after = validate_success(api.get_preparer(preparer["id"], OM), 200)
        assert after["tier"] == "MASTER"


class TestOfficeManagerCannotScopeClaims:
    def test_office_manager_scope_is_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint —
        or that fails an entity-backed ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /tax/claims/{id}/scope is authorized for CaseManager
        only.

        Design: Corner/rbac/office_manager_cannot_scope_claims
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        res = api.scope_claim(ctx["claim"]["id"],
                              {"scope": "IN_SCOPE", "error_attribution": "PREPARER_ERROR"}, OM)
        validate_error(res, "ERR_FORBIDDEN")


class TestCaseManagerCannotFileReturns:
    def test_case_manager_file_is_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint —
        or that fails an entity-backed ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /tax/returns/{id}/file is authorized for OfficeManager
        only.

        Design: Corner/rbac/case_manager_cannot_file_returns
        """
        office, preparer, client = setup_office_preparer_client()
        ret = create_return(client["id"], office["id"], preparer["id"], components=["1040_SIMPLE"])
        res = api.file_return(ret["id"], CM)
        validate_error(res, "ERR_FORBIDDEN")


class TestPreparerCannotCompleteOthersRemediation:
    def test_other_preparer_complete_is_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Preparer`, `X-User-ID` is the
        `id` of the acting `Preparer`; completing a remediation action
        requires that the remediation's `preparer_id` equal `X-User-ID`."
        PRD §2.1: "A request whose role is not permitted for the endpoint —
        or that fails an entity-backed ownership check — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/preparer_cannot_complete_others_remediation
        """
        office = create_office()
        prep1 = create_preparer(office["id"], full_name="P One")
        prep2 = create_preparer(office["id"], full_name="P Two")
        rm = get_success_data(api.create_remediation(
            create_remediation_payload(prep1["id"], due_at="2027-01-01T00:00:00Z"), OM))
        res = api.complete_remediation(rm["id"], make_preparer_headers(prep2["id"]))
        validate_error(res, "ERR_FORBIDDEN")
        after = validate_success(api.get_remediation(rm["id"], OM), 200)
        assert after["status"] == "OPEN"


class TestUnauthenticatedRequestRejected:
    def test_missing_identity_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`
        and `X-User-Role`. A request missing either header, or presenting an
        `X-User-Role` value that is not one of the declared roles, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        res = api.create_office({"name": "Office One", "region_code": "CA"}, headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")
