"""Projects, catalog foundations, and the auth/RBAC error gates."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, NO_AUTH_HEADERS, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    create_project_payload, create_product_type_payload,
)

CE = TEST_USERS["ce_headers"]


class TestProjectCreation:
    def test_project_create_returns_defaults_and_system_fields(self, api, pm_headers):
        """PRD §3.1: "The new project begins with its `status` in `DISCOVERY`,
        with `mock_runs_used` at zero and `cutoff_business_date` null."
        PRD §2.5: "The `version` is an integer starting at creation and
        incrementing by exactly one on every mutation."

        Design: Corner/entities/project_create_returns_defaults_and_system_fields
        """
        resp = api.create_project(
            {
                "institution_name": "Prairie Community CU",
                "incumbent_core_name": "LegacyCore",
                "target_core_name": "Fiserv DNA",
            },
            pm_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DISCOVERY"
        assert data["mock_runs_used"] == 0
        assert data["cutover_scheduled_date"] is None
        assert data["version"] == 1
        assert data["id"]
        assert data["created_at"]
        assert data["updated_at"]


class TestProjectLookup:
    def test_project_get_not_found_returns_404(self, api, pm_headers):
        """PRD §5: "`ERR_NOT_FOUND` | 404".

        Design: Corner/entities/project_get_not_found_returns_404
        """
        resp = api.get_project(NON_EXISTENT_UUID, pm_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthAndRoleGates:
    def test_request_without_headers_is_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_missing_headers
        """
        resp = api.list_projects(NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_trainer_cannot_create_project(self, api, trainer_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/errors/err_forbidden_wrong_role
        """
        resp = api.create_project(create_project_payload(), trainer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_communications_officer_cannot_manage_products(self, api, pm_headers,
                                                           co_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/communications_officer_cannot_manage_products
        """
        project = create_project()
        resp = api.create_product_type(
            create_product_type_payload(project["id"]), co_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestProductCatalog:
    def test_product_type_defaults_when_optional_fields_omitted(self, api, pm_headers):
        """PRD §3.2: "and optional `monthly_fee_cents` (default zero, never
        negative), `fee_waiver_threshold_cents` (null meaning the fee is never
        waived), and `minimum_balance_cents` (default zero)."

        Design: Corner/entities/product_type_defaults_applied_when_optional_fields_omitted
        """
        project = create_project()
        data = validate_success(
            api.create_product_type(
                create_product_type_payload(
                    project["id"], product_code="SAV", statement_frequency="QUARTERLY"
                ),
                CE,
            ),
            201,
        )
        assert data["monthly_fee_cents"] == 0
        assert data["fee_waiver_threshold_cents"] is None

    def test_duplicate_product_code_returns_duplicate(self, api, pm_headers, ce_headers):
        """PRD §3.2: "Each product type is created under a `project_id` with a
        `product_code` unique within the project"

        Design: Corner/validations/duplicate_product_code_returns_duplicate
        """
        project = create_project()
        create_product(project["id"], product_code="DDA", active=False)
        resp = api.create_product_type(
            create_product_type_payload(project["id"], product_code="DDA"), ce_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)
        other = create_project(institution_name="Bank B")
        data = validate_success(
            api.create_product_type(
                create_product_type_payload(other["id"], product_code="DDA"), ce_headers
            ),
            201,
        )
        assert data["id"]


class TestGLAccounts:
    def test_gl_accounts_list_paginates(self, api, fc_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/gl_accounts_list_paginates
        """
        project = create_project()
        for code in ("GL-1", "GL-2", "GL-3"):
            create_gl(project["id"], gl_code=code)
        rows1, meta1 = validate_paginated(
            api.list_gl_accounts(fc_headers, params={"project_id": project["id"],
                                                     "limit": 2, "offset": 0})
        )
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_gl_accounts(fc_headers, params={"project_id": project["id"],
                                                     "limit": 2, "offset": 2})
        )
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_gl_variance_visible_immediately_after_mapping(self, api, fc_headers):
        """PRD §3.3: "A successful mapping stores the `gl_account_id`,
        recomputes the referenced GL's expected, converted, and variance
        totals, and increments the project `version`."
        PRD §3.3: "and `variance_cents`, the converted total minus the expected
        total."

        Design: Corner/consistency_model/immediate_consistency_gl_variance_visible_in_same_flow
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"], gl_code="GL-1")
        acct = create_account(
            project["id"], pt["id"],
            legacy_account_number="L-1", opening_principal_cents=424242,
        )
        map_account(acct["id"], gl["id"], project["id"])
        gl_row = get_success_data(api.get_gl_account(gl["id"], fc_headers))
        assert gl_row["expected_balance_cents"] == 424242
        # PRD §3.3: variance is the converted total minus the expected total.
        assert gl_row["variance_cents"] == (
            gl_row["converted_balance_cents"] - 424242
        )


class TestAccountValidation:
    def test_account_create_missing_required_field_is_invalid_request(
            self, api, ce_headers):
        """PRD §3.3: "Accounts are staged onto the conversion by a
        `ConversionEngineer` supplying the `project_id`, the
        `legacy_account_number` from the incumbent core (unique within the
        project), the `account_type` (`DEPOSIT` or `LOAN`), the governing
        `product_type_id`, the `opening_principal_cents` ledger balance at
        freeze (never negative), the `statement_cycle_day` of month on which
        the statement cycle closes (an integer from 1 to 28), and the
        `accrual_start_date` from which interest begins accruing."

        Design: Corner/entities/account_create_missing_required_field_returns_invalid_request
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA", rate=0.01)
        payload = {
            "project_id": project["id"],
            "legacy_account_number": "L-1",
            "account_type": "DEPOSIT",
            "product_type_id": pt["id"],
            "statement_cycle_day": 1,
            "accrual_start_date": "2026-09-01",
        }
        resp = api.create_account(payload, ce_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_type_enum_rejected(self, api, ce_headers):
        """PRD §3.3: "the `account_type` (`DEPOSIT` or `LOAN`)"

        Design: Corner/entities/account_type_enum_rejected
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA", rate=0.01)
        payload = {
            "project_id": project["id"],
            "legacy_account_number": "L-2",
            "account_type": "MORTGAGE",
            "product_type_id": pt["id"],
            "opening_principal_cents": 100,
            "statement_cycle_day": 1,
            "accrual_start_date": "2026-09-01",
        }
        resp = api.create_account(payload, ce_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_list_filtered_by_status(self, api, ce_headers):
        """PRD §3.3: "the account begins in `STAGED` status with `gl_account_id`
        null and `frozen_flag` false."

        Design: Corner/endpoints/account_list_filtered_by_status
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA", rate=0.01)
        gl = create_gl(project["id"], gl_code="GL-1")
        a1 = create_account(project["id"], pt["id"], legacy_account_number="L-1",
                            opening_principal_cents=1000)
        create_account(project["id"], pt["id"], legacy_account_number="L-2",
                       opening_principal_cents=2000)
        map_account(a1["id"], gl["id"], project["id"])
        rows, meta = validate_paginated(
            api.list_accounts(ce_headers, params={"project_id": project["id"],
                                                  "status": "MAPPED"})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == a1["id"]

